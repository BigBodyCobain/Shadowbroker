#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');

const root = path.resolve(__dirname, '..');
const iconsDir = path.join(root, 'src-tauri', 'icons');

const pngOutputs = {
  '32x32.png': 32,
  '128x128.png': 128,
  '128x128@2x.png': 256,
  'icon.png': 512,
  'Square30x30Logo.png': 30,
  'Square44x44Logo.png': 44,
  'Square71x71Logo.png': 71,
  'Square89x89Logo.png': 89,
  'Square107x107Logo.png': 107,
  'Square142x142Logo.png': 142,
  'Square150x150Logo.png': 150,
  'Square284x284Logo.png': 284,
  'Square310x310Logo.png': 310,
  'StoreLogo.png': 50,
};

const internalPngSizes = [16, 32, 64, 128, 256, 512, 1024];

function clamp(value, lower = 0, upper = 1) {
  return Math.max(lower, Math.min(upper, value));
}

function smoothstep(edge0, edge1, value) {
  if (edge0 === edge1) return 0;
  const t = clamp((value - edge0) / (edge1 - edge0));
  return t * t * (3 - 2 * t);
}

function blend(dst, srcRgb, srcAlpha) {
  if (srcAlpha <= 0) return dst;
  const alpha = clamp(srcAlpha);
  const inv = 1 - alpha;
  return [
    Math.round(dst[0] * inv + srcRgb[0] * alpha),
    Math.round(dst[1] * inv + srcRgb[1] * alpha),
    Math.round(dst[2] * inv + srcRgb[2] * alpha),
    255,
  ];
}

function roundedRectAlpha(nx, ny, half, radius, feather) {
  const qx = Math.abs(nx) - (half - radius);
  const qy = Math.abs(ny) - (half - radius);
  const outside = Math.hypot(Math.max(qx, 0), Math.max(qy, 0));
  const inside = Math.min(Math.max(qx, qy), 0);
  const signedDistance = outside + inside - radius;
  return smoothstep(feather, -feather, signedDistance);
}

function drawIcon(size) {
  const pixels = Buffer.alloc(size * size * 4);
  const feather = 2.4 / Math.max(size, 1);
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const nx = ((x + 0.5) / size) * 2 - 1;
      const ny = ((y + 0.5) / size) * 2 - 1;

      const bgAlpha = roundedRectAlpha(nx, ny, 0.93, 0.28, feather);
      if (bgAlpha <= 0) continue;

      const gradientMix = clamp((nx - ny + 2) / 4);
      const bg = [
        Math.round(7 + 8 * gradientMix),
        Math.round(20 + 26 * (1 - gradientMix)),
        Math.round(28 + 42 * gradientMix),
      ];
      let rgba = [bg[0], bg[1], bg[2], Math.round(255 * bgAlpha)];
      const r = Math.hypot(nx, ny);

      const ringDistance = Math.abs(r - 0.53) - 0.085;
      const ringAlpha = smoothstep(feather * 2.2, -feather * 2.2, ringDistance) * bgAlpha;
      rgba = blend(rgba, [27, 196, 157], ringAlpha);

      const glowAlpha = smoothstep(0.74, 0.16, r) * 0.18 * bgAlpha;
      rgba = blend(rgba, [32, 228, 190], glowAlpha);

      const diamondDistance = Math.abs(nx) + Math.abs(ny) - 0.34;
      const diamondAlpha = smoothstep(feather * 2.6, -feather * 2.6, diamondDistance) * bgAlpha;
      rgba = blend(rgba, [13, 41, 45], diamondAlpha);

      const barVDistance = Math.max(Math.abs(nx) - 0.055, Math.abs(ny) - 0.44);
      const barHDistance = Math.max(Math.abs(ny) - 0.055, Math.abs(nx) - 0.44);
      const barAlpha = Math.max(
        smoothstep(feather * 2.6, -feather * 2.6, barVDistance),
        smoothstep(feather * 2.6, -feather * 2.6, barHDistance),
      ) * 0.92 * bgAlpha;
      rgba = blend(rgba, [183, 251, 239], barAlpha);

      const coreDistance = r - 0.108;
      const coreAlpha = smoothstep(feather * 2.4, -feather * 2.4, coreDistance) * bgAlpha;
      rgba = blend(rgba, [244, 255, 253], coreAlpha);

      const index = (y * size + x) * 4;
      pixels[index] = rgba[0];
      pixels[index + 1] = rgba[1];
      pixels[index + 2] = rgba[2];
      pixels[index + 3] = rgba[3];
    }
  }
  return pixels;
}

function crc32(buffer) {
  let crc = ~0;
  for (let i = 0; i < buffer.length; i += 1) {
    crc ^= buffer[i];
    for (let j = 0; j < 8; j += 1) {
      crc = (crc >>> 1) ^ (0xEDB88320 & -(crc & 1));
    }
  }
  return (~crc) >>> 0;
}

function chunk(type, data) {
  const out = Buffer.alloc(8 + data.length + 4);
  out.writeUInt32BE(data.length, 0);
  out.write(type, 4, 4, 'ascii');
  data.copy(out, 8);
  out.writeUInt32BE(crc32(Buffer.concat([Buffer.from(type, 'ascii'), data])), out.length - 4);
  return out;
}

function encodePng(size, rgba) {
  const stride = size * 4;
  const rows = [];
  for (let y = 0; y < size; y += 1) {
    rows.push(Buffer.from([0]));
    rows.push(rgba.subarray(y * stride, (y + 1) * stride));
  }
  const raw = Buffer.concat(rows);
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]),
    chunk('IHDR', Buffer.from([
      (size >>> 24) & 0xff,
      (size >>> 16) & 0xff,
      (size >>> 8) & 0xff,
      size & 0xff,
      (size >>> 24) & 0xff,
      (size >>> 16) & 0xff,
      (size >>> 8) & 0xff,
      size & 0xff,
      8,
      6,
      0,
      0,
      0,
    ])),
    chunk('IDAT', zlib.deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

function writeIco(targetPath, pngData) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(1, 4);

  const entry = Buffer.alloc(16);
  entry.writeUInt8(0, 0);
  entry.writeUInt8(0, 1);
  entry.writeUInt8(0, 2);
  entry.writeUInt8(0, 3);
  entry.writeUInt16LE(1, 4);
  entry.writeUInt16LE(32, 6);
  entry.writeUInt32LE(pngData.length, 8);
  entry.writeUInt32LE(22, 12);

  fs.writeFileSync(targetPath, Buffer.concat([header, entry, pngData]));
}

function writeIcns(targetPath, pngBySize) {
  const typeMap = new Map([
    [16, 'icp4'],
    [32, 'icp5'],
    [64, 'icp6'],
    [128, 'ic07'],
    [256, 'ic08'],
    [512, 'ic09'],
    [1024, 'ic10'],
  ]);

  const blocks = [];
  for (const [size, type] of typeMap) {
    const png = pngBySize.get(size);
    if (!png) continue;
    const header = Buffer.alloc(8);
    header.write(type, 0, 4, 'ascii');
    header.writeUInt32BE(png.length + 8, 4);
    blocks.push(header, png);
  }

  const payload = Buffer.concat(blocks);
  const icnsHeader = Buffer.alloc(8);
  icnsHeader.write('icns', 0, 4, 'ascii');
  icnsHeader.writeUInt32BE(payload.length + 8, 4);
  fs.writeFileSync(targetPath, Buffer.concat([icnsHeader, payload]));
}

fs.mkdirSync(iconsDir, { recursive: true });

const pngBySize = new Map();
for (const size of internalPngSizes) {
  pngBySize.set(size, encodePng(size, drawIcon(size)));
}

for (const [filename, size] of Object.entries(pngOutputs)) {
  fs.writeFileSync(path.join(iconsDir, filename), pngBySize.get(size) ?? encodePng(size, drawIcon(size)));
}

writeIco(path.join(iconsDir, 'icon.ico'), pngBySize.get(256));
writeIcns(path.join(iconsDir, 'icon.icns'), pngBySize);

const created = fs.readdirSync(iconsDir).sort();
console.log(`Generated ${created.length} desktop icons in ${iconsDir}`);
for (const name of created) {
  console.log(`  - ${name}`);
}
