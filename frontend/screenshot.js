const puppeteer = require('puppeteer');
(async () => {
  const browser = await puppeteer.launch({ headless: "new" });
  const page = await browser.newPage();
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle0' });
  // Ensure we are in light mode
  await page.evaluate(() => {
    localStorage.setItem('ce-theme', 'light');
    document.documentElement.classList.remove('dark');
  });
  await page.screenshot({ path: '/Users/darshann/.gemini/antigravity/brain/d83f3aa5-c33c-40cf-8fbc-010b28aeb30d/light_mode_debug.png' });
  await browser.close();
})();
