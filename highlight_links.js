// highlight_links.js
// This is a test extension for openWeb

(function() {
    // Wait until the page is fully loaded
    document.addEventListener("DOMContentLoaded", () => {
        const links = document.querySelectorAll("a");
        links.forEach(link => {
            link.style.backgroundColor = "yellow";
            link.style.color = "black";
            link.style.fontWeight = "bold";
        });
        console.log("[highlight_links] All links have been highlighted!");
    });
})();
