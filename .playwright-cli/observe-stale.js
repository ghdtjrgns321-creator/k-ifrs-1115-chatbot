async (page) => {
  await page.evaluate(() => {
    window._staleLog = []
    const obs = new MutationObserver(muts => {
      for (const m of muts) {
        if (m.attributeName === 'data-stale') {
          window._staleLog.push(m.target.tagName + ':' + m.target.getAttribute('data-stale'))
        }
      }
    })
    obs.observe(document.body, { attributes: true, subtree: true, attributeFilter: ['data-stale'] })
  })
}
