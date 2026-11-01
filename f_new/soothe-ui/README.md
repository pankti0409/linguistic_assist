# Soothe UI
Reusable, calm, accessible components. No build step, no dependencies.

1. Include `css/soothe.css` and `js/soothe.js` (see `index.html` for markup of every component).
2. Copy any block from `index.html`; class names start with `s-`.
3. Night mode: `<html data-theme="night">` (the `.s-switch` does this for you).

## Connect your AI
```js
document.addEventListener('s:listen-start', () => { /* start camera + mic */ });
document.addEventListener('s:listen-stop', e => {
  e.preventDefault();                       // skip the demo sentence
  Soothe.setModes(['lips','words']);        // lights up the modalities used
  Soothe.setTranscript('I need water.', 0.9); // text + confidence (0 to 1)
});
Soothe.speak('Hello'); Soothe.toast('Saved');
```
Accessibility: 54px+ tap targets, visible focus, aria-live transcript, reduced-motion respected.
