// Small progressive enhancements. Every form still works with JavaScript turned off.

const MB = 1024 * 1024;
const $ = (selector, root = document) => root.querySelector(selector);

function csrfToken() {
  const cookie = document.cookie.split("; ").find((c) => c.startsWith("csrftoken="));
  return cookie ? decodeURIComponent(cookie.split("=")[1]) : ($("[name=csrfmiddlewaretoken]") || {}).value || "";
}

// ---------- Composer: one line until you start writing (left open after a failed post) ----------
document.querySelectorAll(".composer").forEach((form) => {
  const box = $("textarea", form);
  if (!box || box.value || $(".errorlist, .msg.error", form)) return;
  form.classList.add("collapsed");
  form.addEventListener("focusin", () => form.classList.remove("collapsed"), { once: true });
});

// ---------- Sun/moon button: switch the look at once, then save it ----------
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!form.matches("[data-look-switch]")) return;
  event.preventDefault();
  const html = document.documentElement;
  const look = html.dataset.look === "daylight-dark" ? "daylight" : "daylight-dark";
  html.dataset.look = html.dataset.lookPref = look; // a fixed choice now, so theme.js stops following the device
  $('meta[name="theme-color"]').content = look === "daylight-dark" ? "#000000" : "#F2F2F7";
  const body = new FormData(form);
  body.set("look", look);
  fetch(form.action, { method: "POST", body, headers: { "X-Fragment": "1" } })
    .then((response) => { if (!response.ok) throw new Error(String(response.status)); })
    .catch(() => { // not saved: let the server do it with a page load (submit() leaves out the button's own value)
      form.append(Object.assign(document.createElement("input"), { type: "hidden", name: "look", value: look }));
      form.submit();
    });
});

// ---------- Composer: chosen files, and stop an upload the server would refuse ----------
function filesFit(input) {
  const files = [...input.files];
  const total = files.reduce((sum, f) => sum + f.size, 0);
  const limit = Number(input.dataset.maxTotal);
  const label = $("[data-file-names]", input.closest(".composer"));
  const fits = !limit || total <= limit;
  if (label) {
    label.textContent = !fits
      ? `These files add up to ${Math.ceil(total / MB)} MB. One post can carry up to ${limit / MB} MB.`
      : files.length ? `Attached: ${files.map((f) => f.name).join(", ")}` : "";
    label.hidden = !label.textContent;
  }
  return fits;
}

document.addEventListener("change", (event) => {
  const input = event.target;
  if (input.matches(".composer input[type=file]")) filesFit(input);
  if (input.matches(".comment-form input[type=file]") && input.files.length) {
    input.closest(".file-btn").title = `Picture added: ${input.files[0].name}`;
    input.closest(".file-btn").classList.add("on");
  }
  if (input.matches(".look-opt input")) {
    document.querySelectorAll(".look-opt").forEach((opt) => opt.setAttribute("aria-checked", String(opt.contains(input))));
  }
});

// ---------- Forms that update part of the page (reactions, comments, votes, pins) ----------
document.addEventListener("submit", async (event) => {
  const form = event.target;
  const fileInput = $("input[type=file][data-max-total]", form);
  if (fileInput && !filesFit(fileInput)) {
    event.preventDefault();
    return;
  }
  if (form.dataset.confirm && !confirm(form.dataset.confirm)) {
    event.preventDefault();
    return;
  }
  if (!form.dataset.swap) return;
  event.preventDefault();
  const target = $(form.dataset.swap);
  try {
    const body = new FormData(form);
    if (event.submitter && event.submitter.name) body.append(event.submitter.name, event.submitter.value);
    const response = await fetch(form.action, { method: "POST", body, headers: { "X-Fragment": "1" } });
    if (response.redirected) {
      location.reload(); // e.g. new house rules to accept, or signed out: let the server show that page
      return;
    }
    if (response.status === 429 || response.status === 400) {
      alert(await response.text());
      return;
    }
    if (!response.ok) throw new Error(String(response.status));
    target.outerHTML = await response.text();
    if (form.classList.contains("comment-form")) $(`${form.dataset.swap} .comment-form input[name=body]`)?.focus();
    markLongPosts();
  } catch {
    form.submit(); // fall back to a normal page load
  }
});

// ---------- Clicks: menus, copy, show more, translate, reply, formatting ----------
document.addEventListener("click", async (event) => {
  document.querySelectorAll("details.dropdown[open]").forEach((menu) => {
    if (!menu.contains(event.target)) menu.removeAttribute("open");
  });
  const el = event.target.closest("[data-copy],[data-show-more],[data-translate],[data-reply],[data-wrap],[data-prefix],[data-focus],[data-push-enable],[data-push-disable]");
  if (!el) return;

  if (el.dataset.copy !== undefined) {
    await navigator.clipboard.writeText($(el.dataset.copy).innerText);
    el.lastChild.textContent = " Copied";
    el.closest("details")?.removeAttribute("open");
  } else if (el.dataset.showMore !== undefined) {
    el.previousElementSibling.classList.toggle("clamp");
    el.textContent = el.previousElementSibling.classList.contains("clamp") ? "Show more" : "Show less";
  } else if (el.dataset.translate) {
    const box = el.dataset.into ? $(el.dataset.into) : el.nextElementSibling;
    if (!box.hidden) { box.hidden = true; return; }
    el.disabled = true;
    const response = await fetch(el.dataset.translate, { method: "POST", headers: { "X-CSRFToken": csrfToken() } });
    const data = await response.json().catch(() => ({ error: "The translation service didn't answer." }));
    el.disabled = false;
    if (data.html) box.innerHTML = data.html; // escaped by the server
    else box.textContent = data.error;
    box.hidden = false;
  } else if (el.dataset.reply) {
    const form = $(".comment-form", el.closest("article"));
    form.elements.parent.value = el.dataset.reply;
    form.elements.body.placeholder = `Reply to ${el.dataset.name}…`;
    form.elements.body.focus();
  } else if (el.dataset.focus) {
    const field = $(el.dataset.focus);
    if (field) { event.preventDefault(); field.focus(); }
  } else if (el.dataset.wrap || el.dataset.prefix) {
    const field = document.getElementById(el.dataset.target);
    const { selectionStart: start, selectionEnd: end, value } = field;
    if (el.dataset.wrap) {
      const mark = el.dataset.wrap;
      const chosen = value.slice(start, end) || "text";
      field.setRangeText(mark + chosen + mark, start, end, "end");
    } else {
      const lineStart = value.lastIndexOf("\n", start - 1) + 1;
      field.setRangeText(el.dataset.prefix, lineStart, lineStart, "end");
    }
    field.focus();
  } else if (el.dataset.pushEnable) {
    enablePush(el);
  } else if (el.dataset.pushDisable !== undefined) {
    disablePush(el);
  }
});

// Long posts are cut to a few lines with "Show more"; short ones don't need the button.
function markLongPosts() {
  document.querySelectorAll(".post-body.clamp").forEach((body) => {
    const button = body.nextElementSibling;
    if (button && button.dataset.showMore !== undefined) button.hidden = body.scrollHeight <= body.clientHeight + 2;
  });
}
markLongPosts();

// ---------- Suggestions: @mentions while writing, and search while typing ----------
let suggestBox = null;
function closeSuggest() { suggestBox?.remove(); suggestBox = null; }

function showSuggest(anchor, items, onPick) {
  closeSuggest();
  if (!items.length) return;
  suggestBox = document.createElement("div");
  suggestBox.className = "menu";
  suggestBox.style.position = "absolute";
  const box = anchor.getBoundingClientRect();
  suggestBox.style.left = `${box.left + window.scrollX}px`;
  suggestBox.style.top = `${box.bottom + window.scrollY + 4}px`;
  suggestBox.style.right = "auto";
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = item.label;
    if (item.detail) {
      const detail = document.createElement("span");
      detail.className = "small muted";
      detail.textContent = ` · ${item.detail}`;
      button.append(detail);
    }
    button.addEventListener("mousedown", (e) => { e.preventDefault(); onPick(item); closeSuggest(); });
    suggestBox.append(button);
  }
  document.body.append(suggestBox);
}

let typingTimer;
// Makes single sign-on answer 403 instead of a redirect that a background request can't follow.
const XHR = { "X-Requested-With": "XMLHttpRequest" };
document.addEventListener("input", (event) => {
  const field = event.target;
  clearTimeout(typingTimer);
  if (field.matches("[data-mentions]")) {
    const before = field.value.slice(0, field.selectionStart);
    const match = before.match(/(?:^|\s)@([\p{L}'-]{2,30})$/u);
    if (!match) return closeSuggest();
    typingTimer = setTimeout(async () => {
      const response = await fetch(`/people/suggest/?q=${encodeURIComponent(match[1])}`, { headers: XHR });
      if (!response.ok) return closeSuggest(); // e.g. single sign-on's re-check is due: the next page load does it
      const { people } = await response.json();
      showSuggest(field, people.map((p) => ({ label: p.name, detail: p.detail })), (item) => {
        const start = field.selectionStart - match[1].length - 1;
        field.setRangeText(`@${item.label} `, start, field.selectionStart, "end");
        field.focus();
      });
    }, 200);
  } else if (field.dataset.suggest) {
    if (field.value.trim().length < 2) return closeSuggest();
    typingTimer = setTimeout(async () => {
      const response = await fetch(`${field.dataset.suggest}?q=${encodeURIComponent(field.value.trim())}`, { headers: XHR });
      if (!response.ok) return closeSuggest();
      const { results } = await response.json();
      showSuggest(field, results.map((r) => ({ label: r.title, detail: r.section, url: r.url })), (item) => { location.href = item.url; });
    }, 200);
  }
});
document.addEventListener("focusout", () => setTimeout(closeSuggest, 150));
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeSuggest(); });

// ---------- Push notifications ----------
function urlBase64ToBytes(text) {
  const padded = (text + "=".repeat((4 - (text.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
}

function pushStatus(text) {
  const status = $("[data-push-status]");
  if (status) status.textContent = text;
}

async function enablePush(button) {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    pushStatus("This browser can't receive push notifications. On an iPhone, add the hub to your home screen first.");
    return;
  }
  if ((await Notification.requestPermission()) !== "granted") {
    pushStatus("Notifications are blocked for this site. Allow them in your browser or phone settings, then try again.");
    return;
  }
  try {
    const registration = await navigator.serviceWorker.register("/sw.js");
    await navigator.serviceWorker.ready;
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToBytes(button.dataset.pushEnable),
    });
    const response = await fetch(button.dataset.subscribe, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify(subscription),
    });
    pushStatus(response.ok ? "Push notifications are on for this device." : "That didn't work. Please try again.");
  } catch {
    // e.g. the browser's push service is switched off or unreachable, or a private window.
    pushStatus("This browser refused to turn on push notifications. Try again, or use another browser.");
  }
}

async function disablePush(button) {
  const registration = await navigator.serviceWorker?.getRegistration("/");
  const subscription = await registration?.pushManager.getSubscription();
  if (subscription) {
    await fetch(button.dataset.unsubscribe, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify({ endpoint: subscription.endpoint }),
    });
    await subscription.unsubscribe();
  }
  pushStatus("Push notifications are off for this device.");
}
