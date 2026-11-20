// One chat: fetch new messages while the page is on screen, and send without reloading.
// With JavaScript turned off the form posts normally and the page reloads.

const log = document.querySelector(".chat-log");
const form = document.querySelector(".chat-composer");

if (log && form) {
  const text = form.querySelector("textarea");
  const picture = form.querySelector("input[type=file]");
  const pictureName = form.querySelector("[data-file-name]");
  const sendButton = form.querySelector(".chat-send");
  const nearBottom = () => log.scrollHeight - log.scrollTop - log.clientHeight < 80;
  const toBottom = () => { log.scrollTop = log.scrollHeight; };
  let busy = false;
  let again = false;

  async function poll() {
    if (document.hidden) return;
    if (busy) { // a check is under way: run one more when it ends, so nothing sent meanwhile waits 4 seconds
      again = true;
      return;
    }
    busy = true;
    try {
      // The header makes single sign-on answer 403 when its 15-minute re-check is due, instead of a redirect
      // the browser can't follow here. Only a full page load can do the re-check.
      const response = await fetch(`${log.dataset.pollUrl}?after=${log.dataset.lastId}`, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (response.status === 403) {
        if (!text.value.trim() && !picture.files.length) location.reload(); // never throw away a half-typed message
        return;
      }
      if (response.redirected || response.status === 404) {
        location.reload(); // signed out, new house rules to accept, or no longer in this chat
        return;
      }
      if (!response.ok) return;
      const data = await response.json();
      if (data.last_id > Number(log.dataset.lastId)) {
        const stick = nearBottom(); // someone reading older messages is left where they are
        log.querySelector("[data-chat-empty]")?.remove();
        log.insertAdjacentHTML("beforeend", data.html);
        log.dataset.lastId = data.last_id;
        if (stick) toBottom();
      }
    } catch {
      // Offline or a server hiccup: the next round tries again.
    } finally {
      busy = false;
      if (again) {
        again = false;
        poll();
      }
    }
  }

  function showPictureName() {
    pictureName.textContent = picture.files.length ? `Picture: ${picture.files[0].name}` : "";
    pictureName.hidden = !pictureName.textContent;
  }

  toBottom();
  setInterval(poll, 4000);
  document.addEventListener("visibilitychange", poll); // catch up as soon as the tab is looked at again
  picture.addEventListener("change", showPictureName);

  text.addEventListener("keydown", (event) => {
    // Enter sends on a keyboard and Shift+Enter starts a new line. Phones keep Enter for new lines.
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing && matchMedia("(pointer: fine)").matches) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (sendButton.disabled || (!text.value.trim() && !picture.files.length)) return;
    sendButton.disabled = true;
    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { "X-Fragment": "1" },
      });
      if (response.redirected) {
        location.reload();
        return;
      }
      if (response.status === 400 || response.status === 429) {
        alert(await response.text()); // e.g. not a picture, or the activity limit
        return;
      }
      if (!response.ok) throw new Error(String(response.status));
      form.reset();
      showPictureName();
      toBottom();
      poll(); // the new message arrives the same way as everyone else's
    } catch {
      alert("That didn't send. Check your connection and try again."); // the typed text stays in the box
    } finally {
      sendButton.disabled = false;
      text.focus();
    }
  });
}
