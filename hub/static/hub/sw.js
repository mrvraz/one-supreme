// Service worker: shows push notifications and opens the right page when one is tapped.

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = {};
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "New notification", {
      body: data.body || "",
      tag: data.tag,
      icon: "/icon.svg",
      badge: "/icon.svg",
      data: { url: data.url || "/notifications/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data.url, self.location.origin);
  // Only ever open pages of this site.
  const url = target.origin === self.location.origin ? target.href : `${self.location.origin}/notifications/`;
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((open) => {
      for (const client of open) {
        if (client.url === url && "focus" in client) return client.focus();
      }
      return clients.openWindow(url);
    }),
  );
});
