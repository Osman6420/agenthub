import "@testing-library/jest-dom/vitest";

// jsdom lacks a few APIs React Flow touches during render. Provide minimal stubs so the
// canvas can mount in component tests.
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub;

if (!("matchMedia" in globalThis)) {
  (globalThis as unknown as { matchMedia: unknown }).matchMedia = () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  });
}

if (!(globalThis as { DOMMatrixReadOnly?: unknown }).DOMMatrixReadOnly) {
  class DOMMatrixReadOnlyStub {
    m22 = 1;
    constructor(_t?: string) {}
  }
  (globalThis as unknown as { DOMMatrixReadOnly: unknown }).DOMMatrixReadOnly = DOMMatrixReadOnlyStub;
}
