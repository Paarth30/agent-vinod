/** Consistent "something is loading" indicator, used anywhere the app is
 * waiting on a network call — Claude, LinkedIn scraping, or a plain fetch. */
export function InlineLoading({ text = 'loading' }: { text?: string }) {
  return <p className="thinking-indicator">&gt; {text}<span className="blink-cursor">█</span></p>
}
