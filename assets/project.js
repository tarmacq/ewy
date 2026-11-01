// Fallback project page, used by 404.html. Project pages are normally
// pre-built by build.py into /work/<id>/; a project added to projects.js
// before the build has been run still opens here, rendered in the browser.

(function () {
  const projects = window.PROJECTS || [];
  const media = window.MEDIA || {};
  const match = window.location.pathname.match(/^\/work\/([^/]+)\/?$/);
  const project = match && projects.find((p) => p.id === match[1]);
  const pageEl = document.getElementById("project-page");
  const notFoundEl = document.getElementById("not-found");

  if (!project || !pageEl) return;

  const esc = (s) =>
    String(s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
    );

  // Optimized copy made by build.py (image or looping video), else original
  const mediaTag = (src, alt, first) => {
    const m = media[src];
    const size = m && m.w ? ` width="${m.w}" height="${m.h}"` : "";
    if (m && m.type === "video") {
      return `<video src="${m.src}" poster="${m.poster}"${size} autoplay muted loop playsinline aria-label="${esc(alt)}"></video>`;
    }
    const loading = first ? 'fetchpriority="high"' : 'loading="lazy"';
    return `<img src="${esc((m && m.src) || src)}" alt="${esc(alt)}"${size} ${loading} decoding="async" />`;
  };

  document.title = `${project.name} | Elian Yagouni`;
  notFoundEl.hidden = true;
  pageEl.hidden = false;
  pageEl.querySelector(".detail__title").textContent = project.name;
  pageEl.querySelector(".detail__subtitle").textContent =
    project.subtitle || "";
  pageEl.querySelector(".detail__description").innerHTML = project.description
    .split(/\n\s*\n/)
    .map((text) => `<p>${esc(text.trim())}</p>`)
    .join("");
  pageEl.querySelector(".detail__gallery").innerHTML = project.photos
    .map((src, i) =>
      mediaTag(src, `${project.name} by Elian Yagouni, ${i + 1}`, i === 0)
    )
    .join("");
})();
