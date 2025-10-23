document.addEventListener('DOMContentLoaded', () => {
  const slides = Array.from(document.querySelectorAll('.slide'));
  if (slides.length === 0) {
    return;
  }

  let currentIndex = slides.findIndex((slide) => slide.classList.contains('active'));
  if (currentIndex === -1) {
    currentIndex = 0;
    slides[currentIndex].classList.add('active');
  }

  setInterval(() => {
    slides[currentIndex].classList.remove('active');
    currentIndex = (currentIndex + 1) % slides.length;
    slides[currentIndex].classList.add('active');
  }, 6000);
});
