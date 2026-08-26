"use strict";

const destination = new URL(
  "/cases/pension/experiment/",
  "https://session.aipol.kaps.or.kr",
);
destination.search = window.location.search;
destination.hash = window.location.hash;
window.location.replace(destination.href);
