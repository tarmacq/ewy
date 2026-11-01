// Home page interactions:
// - Click "Work" to show all projects.
// - Hover a project name to swap in its preview image under the lists.
// - Click a project name to navigate to its page (/work/<id>/).
// - Whether Work is open is persisted in sessionStorage so returning from a
//   project page restores the view.

(function () {
  const projects = window.PROJECTS || [];
  const media = window.MEDIA || {};
  const workToggle = document.getElementById("work-toggle");
  const projectsEl = document.getElementById("projects");
  const previewEl = document.getElementById("preview");

  if (!workToggle || !projectsEl || !previewEl) return;

  const COLUMNS = ["left", "right"];
  const WORK_KEY = "workOpen";

  // Optimized copy made by build.py, or the original if it hasn't run yet
  const previewSrc = (p) =>
    (media[p.previewImage] && media[p.previewImage].src) || p.previewImage;

  // One ready-made <img> per project, all loaded and decoded up front.
  // Hovering only switches which one is shown, so swaps are instant.
  const previewImages = new Map();
  projects.forEach((p) => {
    const src = previewSrc(p);
    if (previewImages.has(src)) return;
    const img = new Image();
    img.alt = "";
    img.hidden = true;
    img.decoding = "async";
    img.src = src;
    if (img.decode) img.decode().catch(() => {});
    previewEl.appendChild(img);
    previewImages.set(src, img);
  });

  // Same markup build.py writes into index.html, so crawlers see the links
  const renderProjects = () => {
    // Each project names its column; anything without one goes on the right
    const columns = COLUMNS.map((name) =>
      projects.filter((p) => (p.column || "right") === name)
    );
    projectsEl.innerHTML = columns
      .map(
        (col) =>
          `<div class="projects__column">${col
            .map(
              (p) =>
                `<a class="project-link" href="/work/${encodeURIComponent(
                  p.id
                )}/" data-preview="${previewSrc(p)}">${p.name}</a>`
            )
            .join("")}</div>`
      )
      .join("");
  };

  // Place the preview under the project lists, with its right edge lined up
  // with the end of the ANCA title, by telling the CSS where both end
  const ALIGN_ID = "anca";
  const updateNavBottom = () => {
    const root = document.documentElement.style;
    const bottom = projectsEl.getBoundingClientRect().bottom;
    root.setProperty("--nav-bottom", bottom + "px");
    const alignLink = projectsEl.querySelector(
      `a[href="/work/${ALIGN_ID}/"]`
    );
    if (alignLink) {
      const right = alignLink.getBoundingClientRect().right;
      root.setProperty(
        "--preview-right",
        document.documentElement.clientWidth - right + "px"
      );
    }
  };
  window.addEventListener("resize", updateNavBottom);
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(updateNavBottom);
  }

  // Only the most recently hovered project may show its image. If its image
  // is still loading it appears as soon as it is ready; a slow or broken image
  // never leaves another project's picture on screen.
  let wantedSrc = null;

  const hidePreview = () => {
    wantedSrc = null;
    previewEl.classList.remove("is-visible");
  };
  const showPreview = (src) => {
    if (src === wantedSrc) return;
    wantedSrc = src;
    const img = previewImages.get(src);
    previewImages.forEach((other) => (other.hidden = other !== img));
    if (!img) return hidePreview();

    if (img.complete && img.naturalWidth) {
      previewEl.classList.add("is-visible");
      return;
    }
    previewEl.classList.remove("is-visible");
    img.addEventListener(
      "load",
      () => {
        if (wantedSrc === src) previewEl.classList.add("is-visible");
      },
      { once: true }
    );
  };

  const setWorkOpen = (open) => {
    workToggle.classList.toggle("is-active", open);
    workToggle.setAttribute("aria-expanded", open ? "true" : "false");
    projectsEl.hidden = !open;
    if (open) {
      renderProjects();
      updateNavBottom();
    } else {
      hidePreview();
    }
    try {
      sessionStorage.setItem(WORK_KEY, open ? "1" : "0");
    } catch (e) {}
  };

  workToggle.addEventListener("click", () => {
    const isOpen = !workToggle.classList.contains("is-active");
    setWorkOpen(isOpen);
  });

  projectsEl.addEventListener("mouseover", (e) => {
    const link = e.target.closest(".project-link");
    if (!link) return;
    showPreview(link.dataset.preview);
  });
  projectsEl.addEventListener("mouseleave", hidePreview);

  // Restore saved state on load; "/?work" (the About page's Work link) opens it
  let savedWork = "0";
  try {
    savedWork = sessionStorage.getItem(WORK_KEY) || "0";
  } catch (e) {}
  if (savedWork === "1" || new URLSearchParams(location.search).has("work")) {
    setWorkOpen(true);
  }
})();
