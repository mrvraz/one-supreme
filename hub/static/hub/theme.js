// Loaded in <head> without "defer", so it runs before the page paints and there is no flash of the wrong look.
// The server sets data-look when someone has picked Daylight or Daylight Dark. "auto" follows the device.
(function () {
  var html = document.documentElement;
  var dark = window.matchMedia("(prefers-color-scheme: dark)");
  function apply() {
    if (html.dataset.lookPref !== "auto") return;
    html.dataset.look = dark.matches ? "daylight-dark" : "daylight";
    var bar = document.querySelector('meta[name="theme-color"]');
    if (bar) bar.content = dark.matches ? "#000000" : "#F2F2F7";
  }
  apply();
  dark.addEventListener("change", apply);
})();
