// dark_mode.js
(function() {
  console.log("[Ext] Dark Mode loaded");
  const css = `
    html, body {
      background-color: #111 !important;
      color: #ddd !important;
    }
    a { color: #4dabf7 !important; }
    img { filter: brightness(0.8) contrast(1.2); }
  `;
  const style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);
})();
