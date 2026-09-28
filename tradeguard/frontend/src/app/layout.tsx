import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TradeGuard",
  description: "Multi-account MT5 risk desk",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="light" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet" />
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var look=localStorage.getItem('tg-look');var theme=localStorage.getItem('tg-theme');if(look!=='rail'){theme='light';localStorage.setItem('tg-theme','light');localStorage.setItem('tg-look','rail');}document.documentElement.dataset.theme=theme||'light';}catch(e){}`,
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
