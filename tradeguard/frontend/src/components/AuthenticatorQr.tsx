"use client";

import QRCode from "qrcode";
import { useEffect, useState } from "react";

export function AuthenticatorQr({ uri, secret }: { uri: string; secret: string }) {
  const [image, setImage] = useState("");
  const [showKey, setShowKey] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!uri) {
      setImage("");
      return;
    }
    QRCode.toDataURL(uri, { margin: 1, width: 196, errorCorrectionLevel: "M", color: { dark: "#111111", light: "#ffffff" } })
      .then((url) => {
        if (!cancelled) setImage(url);
      })
      .catch(() => {
        if (!cancelled) setImage("");
      });
    return () => {
      cancelled = true;
    };
  }, [uri]);

  return (
    <div className="mb-3">
      <p className="text-sm text-muted mb-3">Scan this code with Google Authenticator, then enter the 6-digit code below.</p>
      {image ? (
        <img src={image} alt="Google Authenticator QR code" width={196} height={196} className="bg-white rounded p-2" />
      ) : (
        <p className="text-sm text-muted">The QR code is not available. Use the setup key.</p>
      )}
      <button type="button" className="ghost mt-3" onClick={() => setShowKey((open) => !open)}>
        {showKey ? "Hide setup key" : "Use a setup key instead"}
      </button>
      {showKey ? (
        <div className="mt-3">
          <p className="text-xs text-muted mb-1">In Google Authenticator choose Enter a setup key. The key type is time based.</p>
          <p className="num break-all text-sm">{secret}</p>
        </div>
      ) : null}
    </div>
  );
}
