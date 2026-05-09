import "./globals.css";

export const metadata = {
  title: "PBX Agent Performance",
  description: "FreePBX call-center performance dashboard",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
