import type { Metadata, Viewport } from 'next'
import { Atkinson_Hyperlegible, Newsreader } from 'next/font/google'
import './globals.css'

// Atkinson Hyperlegible was drawn for low-vision readers: the UI voice.
// Newsreader is reserved for the patient's own sentences, so a message reads like speech.
const ui = Atkinson_Hyperlegible({ subsets: ['latin'], weight: ['400', '700'], variable: '--font-ui', display: 'swap' })
const message = Newsreader({ subsets: ['latin'], variable: '--font-message', display: 'swap' })

export const metadata: Metadata = {
  title: 'Sampark | Multimodal Communication Assistant',
  description: 'A calm assistive communication bridge for people who cannot speak reliably.',
  icons: {
    icon: [
      { url: '/icon-light-32x32.png', media: '(prefers-color-scheme: light)' },
      { url: '/icon-dark-32x32.png', media: '(prefers-color-scheme: dark)' },
      { url: '/icon.svg', type: 'image/svg+xml' },
    ],
    apple: '/apple-icon.png',
  },
}

export const viewport: Viewport = {
  colorScheme: 'light dark',
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#f8f5ef' },
    { media: '(prefers-color-scheme: dark)', color: '#121619' },
  ],
}

// Applies the saved or system theme before first paint, so there is no flash.
const themeScript = `try{var t=localStorage.getItem('ps16.theme');if(t)t=JSON.parse(t);if(t!=='light'&&t!=='dark')t=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';document.documentElement.dataset.theme=t}catch(e){document.documentElement.dataset.theme='light'}`

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  // No analytics: this app is local and private by design (R8).
  return (
    <html lang="en" className={`${ui.variable} ${message.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="antialiased">{children}</body>
    </html>
  )
}
