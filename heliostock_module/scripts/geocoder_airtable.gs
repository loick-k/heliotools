/**
 * Géocodage gratuit des installations solaire thermique (table "BDD STH")
 * via le service Maps natif de Google Apps Script (Maps.newGeocoder()),
 * puis écriture des coordonnées directement dans Airtable.
 *
 * Avantage : contrairement à l'API Geocoding "classique" (payante au-delà
 * d'un quota mensuel), le service Maps d'Apps Script est gratuit, avec un
 * quota journalier intégré, sans carte bancaire ni clé API à configurer.
 *
 * ------------------------------------------------------------------
 * INSTALLATION
 * ------------------------------------------------------------------
 * 1. Dans Airtable, ajoutez deux champs à la table "BDD STH" :
 *      - "Latitude"  (type Number, décimales activées)
 *      - "Longitude" (type Number, décimales activées)
 *
 * 2. Créez votre Personal Access Token Airtable (airtable.com/create/tokens)
 *    avec les scopes :
 *      - data.records:read
 *      - data.records:write   <-- nécessaire ici en plus de la lecture
 *    et donnez-lui accès à la base "BDD Atlansun Solaire thermique".
 *
 * 3. Allez sur https://script.google.com > Nouveau projet, collez ce code.
 *
 * 4. Dans le projet : icône ⚙️ "Paramètres du projet" > "Propriétés du
 *    script" > ajoutez :
 *      AIRTABLE_TOKEN = votre token (pat...)
 *      BASE_ID        = appjauiOQySQq9PBz
 *      TABLE_ID       = tblU1ec0gGyWq9YN8
 *
 * 5. Sélectionnez la fonction "geocodeInstallationsAirtable" et cliquez sur
 *    "Exécuter". Autorisez le script (accès réseau + Maps) lors du premier
 *    lancement.
 *
 * 6. (Optionnel) Pour géocoder automatiquement les nouvelles installations
 *    ajoutées plus tard : icône ⏰ "Déclencheurs" > "Ajouter un déclencheur"
 *    > fonction "geocodeInstallationsAirtable" > déclencheur temporel
 *    (ex : une fois par jour).
 * ------------------------------------------------------------------
 */

function geocodeInstallationsAirtable() {
  const props = PropertiesService.getScriptProperties();
  const token = props.getProperty('AIRTABLE_TOKEN');
  const baseId = props.getProperty('BASE_ID');
  const tableId = props.getProperty('TABLE_ID');

  if (!token || !baseId || !tableId) {
    throw new Error(
      'Configurez AIRTABLE_TOKEN, BASE_ID et TABLE_ID dans ' +
        'Paramètres du projet > Propriétés du script.'
    );
  }

  const geocoder = Maps.newGeocoder().setRegion('fr');
  let offset = null;
  let nbGeocodees = 0;
  let nbEchecs = 0;

  do {
    const url =
      'https://api.airtable.com/v0/' +
      baseId +
      '/' +
      tableId +
      '?pageSize=100' +
      (offset ? '&offset=' + offset : '');

    const response = UrlFetchApp.fetch(url, {
      headers: { Authorization: 'Bearer ' + token },
    });
    const data = JSON.parse(response.getContentText());

    data.records.forEach(function (record) {
      const fields = record.fields;

      // On ne re-géocode pas une installation déjà localisée (économie de quota).
      if (fields.Latitude && fields.Longitude) return;

      const parts = [fields['Application'], fields['Ville'], fields['Département']].filter(
        Boolean
      );
      if (parts.length === 0) return;
      parts.push('France');
      const address = parts.join(', ');

      try {
        const result = geocoder.geocode(address);
        if (result.status === 'OK' && result.results.length > 0) {
          const loc = result.results[0].geometry.location;
          updateAirtableRecord(baseId, tableId, record.id, loc.lat, loc.lng, token);
          Logger.log(address + ' -> ' + loc.lat + ', ' + loc.lng);
          nbGeocodees++;
        } else {
          Logger.log('Échec géocodage : ' + address + ' (statut : ' + result.status + ')');
          nbEchecs++;
        }
      } catch (e) {
        Logger.log('Erreur pour ' + address + ' : ' + e.message);
        nbEchecs++;
      }

      Utilities.sleep(250); // ménage le quota Maps + la limite Airtable (5 req/s)
    });

    offset = data.offset || null;
  } while (offset);

  Logger.log(
    'Terminé : ' + nbGeocodees + ' installation(s) géocodée(s), ' + nbEchecs + ' échec(s).'
  );
}

function updateAirtableRecord(baseId, tableId, recordId, lat, lng, token) {
  const url = 'https://api.airtable.com/v0/' + baseId + '/' + tableId + '/' + recordId;
  UrlFetchApp.fetch(url, {
    method: 'patch',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + token },
    payload: JSON.stringify({ fields: { Latitude: lat, Longitude: lng } }),
  });
}
