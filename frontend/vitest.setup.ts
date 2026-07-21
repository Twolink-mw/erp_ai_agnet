import "@testing-library/jest-dom/vitest";

// recharts의 ResponsiveContainer는 ResizeObserver와 실제 엘리먼트 크기에 의존하는데,
// jsdom은 둘 다 제공하지 않는다 — 폭/높이가 0이면 차트 내부가 렌더링되지 않으므로
// 테스트 환경에서 고정 크기를 갖도록 폴리필한다.
class ResizeObserverPolyfill {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// @ts-expect-error - jsdom에는 ResizeObserver가 없음
global.ResizeObserver = ResizeObserverPolyfill;

Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
  configurable: true,
  value: 500,
});
Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
  configurable: true,
  value: 300,
});
// jsdom은 scrollIntoView를 구현하지 않아 호출 시 TypeError가 발생한다.
Element.prototype.scrollIntoView = function () {};

HTMLElement.prototype.getBoundingClientRect = function () {
  return {
    width: 500,
    height: 300,
    top: 0,
    left: 0,
    right: 500,
    bottom: 300,
    x: 0,
    y: 0,
    toJSON() {},
  } as DOMRect;
};
