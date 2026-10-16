// Kampanya hesabı: test/campaign_vectors.json (aynı dosya Python tarafında da çalışır).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const C = require('../src/campaigns');

const v = JSON.parse(fs.readFileSync(path.join(__dirname, 'campaign_vectors.json'), 'utf8'));

for (const c of v.validate) {
  test(`doğrulama: ${c.name}`, () => {
    if (c.error) assert.throws(() => C.validateCampaign(c.input), (e) => e instanceof C.CampaignError && e.message.includes(c.error));
    else assert.deepEqual(C.validateCampaign(c.input), c.expect);
  });
}
for (const c of v.live) test(`geçerlilik: ${c.name}`, () => assert.equal(C.isLive(c.campaign, c.at, c.customer), c.expect));
for (const c of v.compute) {
  test(`hesap: ${c.name}`, () => assert.deepEqual(C.computeCampaigns(c.order, c.campaigns, { at: c.at, categoryOf: c.categoryOf }), c.expect));
}
