// Render report/report.html to report/report.pdf (A4) with headless Chromium (Playwright).
//   node report/render.cjs
const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('file://' + path.join(__dirname, 'report.html'), { waitUntil: 'networkidle' });
  await page.pdf({
    path: path.join(__dirname, 'report.pdf'),
    format: 'A4',
    printBackground: true,
    displayHeaderFooter: true,
    headerTemplate: '<span></span>',
    footerTemplate: '<div style="font-size:7px;color:#7a7974;width:100%;text-align:center;font-family:sans-serif">' +
      'CS3081 mini project &middot; page <span class="pageNumber"></span> of <span class="totalPages"></span></div>',
    margin: { top: '13mm', bottom: '14mm', left: '14mm', right: '14mm' },
  });
  await browser.close();
  console.log('wrote report/report.pdf');
})();
