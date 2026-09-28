from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.audit import write_audit
from app.models.entities import Account, BrokerCommand, CopyDecision, CopyLink
from tradeguard_risk.types import Decision, ProposedOrder


def propagate_open(db: Session, master: Account, position, event_id: str) -> None:
    links = db.scalars(
        select(CopyLink).where(
            CopyLink.master_account_id == master.id,
            CopyLink.organization_id == master.organization_id,
            CopyLink.enabled.is_(True),
        )
    ).all()
    if not links:
        return
    from app.services.ingest_service import _evaluate, _spec_for, _fx

    for link in links:
        follower = db.get(Account, link.follower_account_id)
        if follower is None or follower.organization_id != master.organization_id:
            continue
        volume = (position.volume * link.volume_scale).quantize(Decimal("0.01"))
        proposed = ProposedOrder(
            position.symbol,
            position.side,
            volume,
            position.entry_price,
            position.stop_loss,
            position.take_profit,
            f"copy-{position.ticket}",
        )
        spec = _spec_for(db, follower, position.symbol)
        try:
            result = _evaluate(
                db,
                follower,
                datetime.now(timezone.utc),
                f"copy:{event_id}:{follower.id}",
                proposed=proposed,
                spec=spec,
                fx=_fx(follower, spec),
            )
        except Exception as exc:  # noqa: BLE001
            _record(db, link, follower, position.ticket, "BLOCK", f"ENGINE_FAILURE {exc.__class__.__name__}")
            continue
        reason = "; ".join(hit.message for hit in result.hits) or result.decision.value
        _record(db, link, follower, position.ticket, result.decision.value, reason[:400])
        if result.decision in {Decision.ALLOW, Decision.WARNING}:
            db.add(
                BrokerCommand(
                    account_id=follower.id,
                    command="COPY_OPEN",
                    detail={
                        "symbol": position.symbol,
                        "side": position.side,
                        "volume": str(volume),
                        "entry": str(position.entry_price),
                        "stop_loss": None if position.stop_loss is None else str(position.stop_loss),
                        "take_profit": None if position.take_profit is None else str(position.take_profit),
                        "master_account_id": str(master.id),
                        "master_ticket": position.ticket,
                        "decision": result.decision.value,
                    },
                )
            )
        else:
            write_audit(
                db,
                organization_id=master.organization_id,
                actor_type="system",
                action="copy_blocked",
                entity_type="account",
                entity_id=str(follower.id),
                after={"master": str(master.id), "ticket": position.ticket, "decision": result.decision.value, "reason": reason[:300]},
            )


def _record(db: Session, link: CopyLink, follower: Account, ticket: str, decision: str, reason: str) -> None:
    db.add(
        CopyDecision(
            link_id=link.id,
            master_ticket=ticket,
            follower_account_id=follower.id,
            decision=decision,
            reason=reason[:400],
        )
    )
