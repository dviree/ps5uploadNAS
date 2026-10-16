// Community game reports: GitHub issues (the "Game report" form), counted by
// a workflow into compat/compat.json in the repository.
import {FileSystem, Http, Platform} from '@ps5-react/core';
import {APP_VERSION} from './version.js';

const REPO = 'theghostonline/PS5-LZ4-Compression';
const COMPAT_URL = `https://raw.githubusercontent.com/${REPO}/main/compat/compat.json`;
const DATA = Platform.OS === 'ps5' ? '/data/LZ4Compression' : `${FileSystem.dataDir}/LZ4Compression`;
const CACHE = `${DATA}/compat-cache.json`;
const REPORTED = `${DATA}/compat-reported.json`;
// A test copy of compat.json can be pointed at with this file.
const COMPAT_OVERRIDE = `${DATA}/compat-url`;

export const REPORT_CHOICES = [
  {status: 'works', label: 'Works', form: 'Works'},
  {status: 'issues', label: 'Works with issues', form: 'Works with issues'},
  {status: 'noStart', label: "Won't start", form: "Won't start (black screen or crash on launch)"},
  {status: 'crash', label: 'Crashes in game', form: 'Crashes in game'},
];

function readJson(path, fallback) {
  try {
    return FileSystem.exists(path) ? JSON.parse(FileSystem.readFile(path)) : fallback;
  } catch (err) {
    return fallback;
  }
}

function writeJson(path, value) {
  try {
    FileSystem.mkdir(DATA, {recursive: true});
    FileSystem.writeFile(path, JSON.stringify(value));
  } catch (err) {
    // Only a cache.
  }
}

// The reports, or the last copy that loaded when GitHub can't be reached.
export async function loadCompat() {
  try {
    let url = COMPAT_URL;
    try {
      if (FileSystem.exists(COMPAT_OVERRIDE)) url = FileSystem.readFile(COMPAT_OVERRIDE).trim() || COMPAT_URL;
    } catch (err) {
      // Use the real list.
    }
    const response = await Http.request(url, {maxBytes: 4 * 1024 * 1024});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const games = data && data.games ? data.games : {};
    writeJson(CACHE, games);
    return games;
  } catch (err) {
    return readJson(CACHE, {});
  }
}

// "Works for 4 of 5", or null when nobody has reported the game yet.
export function compatSummary(entry) {
  if (!entry || !entry.reports) return null;
  const working = (entry.works || 0) + (entry.issues || 0);
  const broken = (entry.noStart || 0) + (entry.crash || 0);
  const text = working && !broken ? `Works for ${entry.reports === 1 ? '1 person' : `all ${entry.reports}`}`
    : !working ? `Broken for ${entry.reports === 1 ? '1 person' : `all ${entry.reports}`}`
    : `Works for ${working} of ${entry.reports}`;
  return {text, tone: broken > working ? 'bad' : broken ? 'warn' : 'good'};
}

export function loadReported() {
  return readJson(REPORTED, {});
}

export function markReported(titleId, status) {
  const all = readJson(REPORTED, {});
  all[titleId] = status;
  writeJson(REPORTED, all);
}

// A prefilled "Game report" issue, short enough to scan off a TV.
export function reportUrl(game, status) {
  const choice = REPORT_CHOICES.find(item => item.status === status) || REPORT_CHOICES[0];
  const name = String(game.name || '').slice(0, 60);
  const params = [
    ['template', 'compat.yml'],
    ['title', `[Game report] ${name || game.titleId}: ${choice.label}`],
    ['title_id', game.titleId],
    ['game', name],
    ['status', choice.form],
    ['game_version', game.version || game.contentVersion || ''],
    ['app_version', APP_VERSION],
  ].filter(([, value]) => value);
  return `https://github.com/${REPO}/issues/new?` +
    params.map(([key, value]) => `${key}=${encodeURIComponent(value)}`).join('&');
}
