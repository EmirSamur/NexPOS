// Mutfak ekranının (hosting/mutfak) kullandığı Firebase web SDK dosyalarını npm paketinden
// kopyalar. Dosyalar birbirini gstatic adresinden içe aktarır; bu adresler yerel yollara
// çevrilir. Böylece tablet her şeyi kafenin kendi Hosting adresinden yükler (CDN gerekmez).
//
// Kullanım (firebase/ klasöründen): node scripts/vendor-firebase-sdk.js
const fs = require('fs');
const path = require('path');

const pkgDir = path.dirname(require.resolve('firebase/package.json', { paths: [path.join(__dirname, '../tests')] }));
const version = require(path.join(pkgDir, 'package.json')).version;
const out = path.join(__dirname, '../hosting/mutfak/vendor');
fs.mkdirSync(out, { recursive: true });
for (const name of ['firebase-app.js', 'firebase-auth.js', 'firebase-firestore.js', 'firebase-functions.js']) {
  const src = fs.readFileSync(path.join(pkgDir, name), 'utf8')
    .replace(/https:\/\/www\.gstatic\.com\/firebasejs\/[\d.]+\/(firebase-[a-z-]+\.js)/g, './$1')
    .replace(/\n\/\/# sourceMappingURL=.*$/m, '');
  fs.writeFileSync(path.join(out, name), src);
}
fs.writeFileSync(path.join(out, 'VERSION'), `${version}\n`);
console.log(`Firebase web SDK ${version} → ${path.relative(process.cwd(), out)}`);
