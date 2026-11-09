/** Лёгкие улучшения UX на клиенте */
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".case-card").forEach((card, index) => {
    card.style.animationDelay = `${index * 0.08}s`;
  });
});
