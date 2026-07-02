/**
 * SATISFY restock monitor — version Google Apps Script (100% gratuit, sans carte).
 *
 * Même logique que check.py :
 *   - dispo par variante via cascade Shopify : {url}.js -> {url}.json -> regex HTML
 *   - alerte ntfy UNIQUEMENT sur transition indisponible -> disponible
 *   - état persistant via PropertiesService (pas de fichier à committer)
 *
 * INSTALLATION (voir apps-script/README.md pour le détail) :
 *   1. https://script.google.com -> Nouveau projet -> colle ce fichier.
 *   2. Renseigne NTFY_TOPIC ci-dessous (ou via les Script Properties).
 *   3. Exécute createTrigger() une fois -> déclencheur toutes les 15 min.
 *   4. Abonne-toi au topic dans l'app ntfy.
 */

// ---------------------------------------------------------------------------
// Configuration. Laisse vide pour lire depuis les Script Properties
// (Paramètres du projet -> Propriétés du script), sinon écris la valeur ici.
// ---------------------------------------------------------------------------
var CONFIG = {
  PRODUCT_URLS: 'https://satisfyrunning.com/products/heatcrush-muscle-tee-moonstruck',
  NTFY_TOPIC: '',                       // <-- REQUIS : ton topic ntfy secret
  NTFY_SERVER: 'https://ntfy.sh',
  NTFY_TOKEN: '',                       // optionnel (topic protégé)
};

var USER_AGENT =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/124.0 Safari/537.36';

var STATE_KEY = 'RESTOCK_STATE';
var AVAILABLE_RE = /"available"\s*:\s*(true|false)/gi;

// ---------------------------------------------------------------------------
// Point d'entrée : à appeler par le déclencheur temporel.
// ---------------------------------------------------------------------------
function checkRestock() {
  var props = PropertiesService.getScriptProperties();
  var cfg = resolveConfig_(props);

  var urls = cfg.PRODUCT_URLS.split(',')
    .map(function (u) { return normalizeUrl_(u.trim()); })
    .filter(function (u) { return u; });
  if (!urls.length) { Logger.log('Aucune URL produit configurée.'); return; }

  if (!cfg.NTFY_TOPIC) {
    Logger.log('NTFY_TOPIC non défini : mode dry-run (aucune notification).');
  }

  var state = loadState_(props);
  var newState = {};
  for (var k in state) newState[k] = state[k]; // conserve les produits non vérifiés
  var restocks = [];

  urls.forEach(function (url) {
    Logger.log('Vérification : ' + url);
    var variants = checkProduct_(url);
    if (variants === null) {
      Logger.log('  échec total, état conservé pour ce produit');
      return;
    }
    variants.forEach(function (v) {
      var prev = state[v.key];
      var prevAvail = prev ? prev.available : null;
      Logger.log('    [' + (v.available ? 'DISPO' : 'indispo') + '] ' + v.title);
      if (prevAvail === false && v.available === true) restocks.push(v);
      newState[v.key] = {
        handle: v.handle,
        title: v.title,
        product_url: v.product_url,
        available: v.available,
        last_checked: new Date().toISOString(),
      };
    });
  });

  if (restocks.length) {
    Logger.log(restocks.length + ' restock(s) détecté(s).');
    restocks.forEach(function (v) {
      var message = v.handle + ' — ' + v.title + ' est de nouveau DISPONIBLE !';
      Logger.log('  ALERTE : ' + message);
      if (cfg.NTFY_TOPIC) sendNtfy_(cfg, '🟢 RESTOCK SATISFY', message, v.product_url);
    });
  } else {
    Logger.log('Aucune nouvelle disponibilité (pas d\'alerte).');
  }

  saveState_(props, newState);
}

// ---------------------------------------------------------------------------
// Cascade Shopify : .js -> .json -> HTML.
// Retourne un tableau de variantes, ou null si les 3 méthodes échouent.
// ---------------------------------------------------------------------------
function checkProduct_(url) {
  var handle = handleFromUrl_(url);

  var data = fetchJson_(url + '.js');
  if (data && Array.isArray(data.variants)) {
    return attachMeta_(handle, url, normalizeVariants_(data.variants));
  }

  data = fetchJson_(url + '.json');
  if (data && data.product && Array.isArray(data.product.variants)) {
    return attachMeta_(handle, url, normalizeVariants_(data.product.variants));
  }

  var html = fetchText_(url);
  if (html) {
    var variants = parseHtml_(html);
    if (variants.length) return attachMeta_(handle, url, variants);
  }

  return null;
}

function normalizeVariants_(raw) {
  return raw.map(function (v) {
    return {
      id: (v.id != null ? v.id : null),
      title: v.title || v.public_title || 'Default',
      available: !!v.available,
    };
  });
}

function parseHtml_(html) {
  var m, anyAvailable = false, found = false;
  AVAILABLE_RE.lastIndex = 0;
  while ((m = AVAILABLE_RE.exec(html)) !== null) {
    found = true;
    if (m[1].toLowerCase() === 'true') anyAvailable = true;
  }
  return found ? [{ id: null, title: '(page)', available: anyAvailable }] : [];
}

function attachMeta_(handle, url, variants) {
  variants.forEach(function (v) {
    v.handle = handle;
    v.product_url = url;
    v.key = handle + '::' + (v.id != null ? v.id : v.title);
  });
  return variants;
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------
function fetchText_(url) {
  try {
    var resp = UrlFetchApp.fetch(url, {
      muteHttpExceptions: true,
      followRedirects: true,
      headers: { 'User-Agent': USER_AGENT, 'Accept': '*/*' },
    });
    if (resp.getResponseCode() !== 200) {
      Logger.log('  ' + url + ' -> HTTP ' + resp.getResponseCode());
      return null;
    }
    return resp.getContentText();
  } catch (e) {
    Logger.log('  requête échouée sur ' + url + ' : ' + e);
    return null;
  }
}

function fetchJson_(url) {
  var text = fetchText_(url);
  if (!text) return null;
  try { return JSON.parse(text); } catch (e) { return null; }
}

// Publication ntfy via JSON (gère proprement l'UTF-8 / les emojis).
function sendNtfy_(cfg, title, message, click) {
  var payload = {
    topic: cfg.NTFY_TOPIC,
    title: title,
    message: message,
    priority: 5,
    tags: ['shopping', 'tshirt', 'green_circle'],
    click: click,
  };
  var options = {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  };
  if (cfg.NTFY_TOKEN) options.headers = { Authorization: 'Bearer ' + cfg.NTFY_TOKEN };
  try {
    var resp = UrlFetchApp.fetch(cfg.NTFY_SERVER.replace(/\/+$/, '') + '/', options);
    if (resp.getResponseCode() >= 300) {
      Logger.log('  ntfy a répondu HTTP ' + resp.getResponseCode() + ' : ' +
        resp.getContentText().slice(0, 200));
    }
  } catch (e) {
    Logger.log('  échec envoi ntfy : ' + e);
  }
}

// ---------------------------------------------------------------------------
// État persistant
// ---------------------------------------------------------------------------
function loadState_(props) {
  var raw = props.getProperty(STATE_KEY);
  if (!raw) return {};
  try { return JSON.parse(raw); } catch (e) { return {}; }
}

function saveState_(props, state) {
  props.setProperty(STATE_KEY, JSON.stringify(state));
  Logger.log('État enregistré (' + Object.keys(state).length + ' variante(s)).');
}

// ---------------------------------------------------------------------------
// Utilitaires
// ---------------------------------------------------------------------------
function resolveConfig_(props) {
  var out = {};
  for (var k in CONFIG) {
    var v = props.getProperty(k);
    out[k] = (v != null && v !== '') ? v : CONFIG[k];
  }
  return out;
}

function normalizeUrl_(url) {
  if (!url) return '';
  url = url.split('?')[0].split('#')[0];
  url = url.replace(/\.(js|json)$/i, '');
  return url.replace(/\/+$/, '');
}

function handleFromUrl_(url) {
  var path = url.replace(/^https?:\/\/[^/]+/i, '');
  var segs = path.split('/').filter(function (s) { return s; });
  return segs.length ? segs[segs.length - 1] : url;
}

// ---------------------------------------------------------------------------
// À exécuter UNE fois pour planifier le bot toutes les 15 minutes.
// ---------------------------------------------------------------------------
function createTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'checkRestock') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('checkRestock').timeBased().everyMinutes(15).create();
  Logger.log('Déclencheur créé : checkRestock toutes les 15 minutes.');
}

// Réinitialise l'état mémorisé (utile pour re-tester une alerte).
function resetState() {
  PropertiesService.getScriptProperties().deleteProperty(STATE_KEY);
  Logger.log('État réinitialisé.');
}
