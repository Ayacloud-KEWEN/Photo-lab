import type { LocaleResource } from "../types";

const fr: LocaleResource = {
  app: {
    name: "LUMEN Studio",
  },
  nav: {
    library: "Photothèque",
    timeline: "Chronologie",
    map: "Carte",
    aiSearch: "Recherche IA",
    collections: "Collections",
    settings: "Réglages",
  },
  topbar: {
    searchPlaceholder: "Rechercher des photos, lieux, appareils, mots-clés…",
    showInspector: "Afficher l’inspecteur",
    hideInspector: "Masquer l’inspecteur",
  },
  status: {
    starting: "Démarrage du service…",
    connected: "Service connecté",
    disconnected: "Connexion au service perdue",
    failed: "Échec du démarrage du service",
    schema: "Base de données v{{version}}",
    roots_one: "{{count}} source",
    roots_other: "{{count}} sources",
  },
  inspector: {
    title: "Inspecteur",
    empty: "Sélectionnez un élément pour afficher ses détails",
    path: "Chemin",
    status: "État",
    availability: "Disponibilité",
    available: "Accessible",
    unavailable: "Inaccessible (disque déconnecté ?)",
    volumeLabel: "Nom du volume",
    volumeSerial: "N° de série du volume",
    addedAt: "Ajouté le",
    lastScanned: "Dernière analyse",
    never: "Jamais",
  },
  library: {
    title: "Photothèque",
    subtitle_one: "{{count}} source de photos",
    subtitle_other: "{{count}} sources de photos",
    emptyTitle: "Créez votre photothèque",
    emptyDescription:
      "Choisissez un dossier local contenant vos photos. LUMEN Studio se contente de lire les fichiers : il ne déplace, ne renomme et ne modifie jamais vos originaux.",
    emptyFormats: "Prend en charge RAW, JPEG, HEIC, MP4 et MOV",
    selectFolder: "Choisir un dossier de photos",
    addFolder: "Ajouter un dossier",
    pickerTitle: "Choisir un dossier de photos",
    sources: "Sources de photos",
    remove: "Retirer",
    removeConfirmTitle: "Retirer la source",
    removeConfirmMessage:
      "Retirer « {{name}} » de la photothèque ?\n\nSeuls les enregistrements d’index de LUMEN Studio sont supprimés. Les fichiers sur le disque ne sont pas touchés.",
    removeConfirmOk: "Retirer",
    cancel: "Annuler",
    scanNotice:
      "L’analyse des médias arrive à la prochaine phase (Phase 2). Les dossiers ajoutés sont mis en file d’attente.",
    connecting: "Connexion au service…",
    backendUnavailable: "Impossible de joindre le service : {{message}}",
    retry: "Réessayer",
    rootStatus: {
      pending_scan: "En attente d’analyse",
      scanning: "Analyse en cours",
      ready: "Prêt",
      offline: "Hors ligne",
      error: "Erreur",
    },
    errors: {
      conflict: "Ce dossier est déjà ajouté ou chevauche un dossier déjà ajouté.",
      invalid_path: "Ce dossier ne peut pas être utilisé : {{message}}",
      network_error: "Impossible de joindre le service.",
      generic: "Échec de l’opération : {{message}}",
    },
  },
  placeholder: {
    comingIn: "Disponible en {{phase}}",
    timeline: "Parcourez photos et vidéos par date de prise de vue.",
    map: "Affichez les photos géolocalisées sur une carte.",
    aiSearch: "Trouvez des photos en les décrivant, p. ex. « un lac sous des montagnes enneigées ».",
    collections: "Organisez vos photos en collections et projets de voyage.",
  },
  settings: {
    title: "Réglages",
    language: "Langue de l’interface",
    languageHint: "Les changements s’appliquent immédiatement.",
    about: "À propos",
    appVersion: "Version de l’application",
    apiVersion: "Version de l’API",
    schemaVersion: "Version du schéma de la base",
    backend: "Service local",
  },
};

export default fr;
