import "./globals.css";
export const metadata = { title: "StocksAnalyzer", description: "S&P 500 research desk" };
export default function RootLayout({children}:{children:React.ReactNode}) {
  return <html lang="en"><body>{children}</body></html>;
}