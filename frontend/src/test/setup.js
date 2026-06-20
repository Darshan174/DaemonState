import "@testing-library/jest-dom";

class TestIntersectionObserver {
  constructor(callback) {
    this.callback = callback;
  }

  observe(element) {
    this.callback?.([{ isIntersecting: true, target: element }], this);
  }

  unobserve() {}

  disconnect() {}
}

if (!globalThis.IntersectionObserver) {
  globalThis.IntersectionObserver = TestIntersectionObserver;
}
