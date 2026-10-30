// Detail page: reads ?id=<slug> from the URL, looks up the project in
// window.PROJECTS, and renders the description + photo gallery.

(function () {
  const projects = window.PROJECTS || [];
  const params = new URLSearchParams(window.location.search);
  const id = params.get("id");
  const project = projects.find((p) => p.id === id);

  const titleEl = document.getElementById("project-title");
  const descEl = document.getElementById("project-description");
  const galleryEl = document.getElementById("project-gallery");

  if (!project) {
    titleEl.textContent = "Not found";
    descEl.textContent = "This project does not exist.";
    return;
  }

  document.title = `${project.name} — Portfolio`;
  titleEl.textContent = project.name;
  document.getElementById("project-subtitle").textContent =
    project.subtitle || "";
  // Blank lines in the description separate paragraphs
  descEl.innerHTML = "";
  project.description.split(/\n\s*\n/).forEach((text) => {
    const p = document.createElement("p");
    p.textContent = text;
    descEl.appendChild(p);
  });
  galleryEl.innerHTML = project.photos
    .map(
      (src, i) =>
        `<img src="${src}" alt="${project.name} — photo ${i + 1}" loading="lazy" />`
    )
    .join("");
})();
