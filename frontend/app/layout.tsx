import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title: 'CaspiFlow — Smart Caspian Transit', description: 'Демонстрационный цифровой двойник каспийского транспортного коридора' };
export default function Layout({ children }: {children: React.ReactNode}) { return <html lang="ru"><body>{children}</body></html>; }
