document.addEventListener("click", async (event) => {
  if (!(event.target instanceof Element)) return;
  const button = event.target.closest("[data-copy-target]");
  if (!(button instanceof HTMLButtonElement)) return;
  const targetId = button.dataset.copyTarget;
  const target = targetId ? document.getElementById(targetId) : null;
  if (!(target instanceof HTMLTextAreaElement)) return;
  const original = button.textContent;
  try {
    await navigator.clipboard.writeText(target.value);
    button.textContent = "Kopyalandı";
  } catch {
    target.focus();
    target.select();
    button.textContent = "Metin seçildi";
  }
  window.setTimeout(() => {
    button.textContent = original;
  }, 1600);
});
