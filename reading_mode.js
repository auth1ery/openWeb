// reading_mode.js
(function() {
  console.log("[Ext] Reading Mode enabled");
  document.querySelectorAll("header, footer, nav, aside, iframe, video, img, button").forEach(e => e.remove());
  document.body.style.maxWidth = "700px";
  document.body.style.margin = "40px auto";
  document.body.style.fontSize = "20px";
  document.body.style.lineHeight = "1.6";
})();
