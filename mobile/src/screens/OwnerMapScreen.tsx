import { useFocusEffect, useNavigation } from "@react-navigation/native";
import { NativeStackNavigationProp } from "@react-navigation/native-stack";
import React, { useCallback, useState } from "react";
import { ActivityIndicator, Text, TouchableOpacity, View } from "react-native";
import { WebView } from "react-native-webview";

import { getOwnerMap } from "../api/owner";
import { OwnerMapPin, OwnerMapResponse } from "../api/types";
import { colors, shared } from "../theme";
import { RootStackParamList } from "../navigation/types";

type Nav = NativeStackNavigationProp<RootStackParamList, "OwnerMap">;

// Pin colours mirror the owner queue's status semantics (theme.ts): pending
// work that needs Anthony's decision is the warning amber, in-flight work is
// the accent teal. Kept in sync with the WebView HTML below.
const PENDING_COLOR = colors.warn; // #a85e0f
const ONGOING_COLOR = colors.accent; // #2f6f7e

// NSW mainland centre — where the map opens when there are no pins yet, so
// Anthony still sees his operating area rather than a world view.
const NSW_CENTRE = { lat: -32.5, lng: 147 };

function escapePins(pins: OwnerMapPin[]): string {
  // Inline the pin data into the WebView HTML. Escape "<" so an address
  // containing a stray angle bracket can never break out of the <script>.
  return JSON.stringify(pins).replace(/</g, "\\u003c");
}

function mapHtml(pins: OwnerMapPin[]): string {
  const pinsJson = escapePins(pins);
  return `<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>
  html, body { height: 100%; margin: 0; padding: 0; background: #e6e9e7; }
  #map { width: 100%; height: 100%; }
  .legend { position: absolute; bottom: 12px; left: 12px; z-index: 1000;
    background: rgba(255,255,255,0.95); border-radius: 8px; padding: 8px 10px;
    font: 600 12px/1.4 -apple-system, "Segoe UI", Roboto, sans-serif; color: #1c232b;
    box-shadow: 0 1px 4px rgba(0,0,0,0.2); }
  .legend .row { display: flex; align-items: center; gap: 6px; }
  .dot { width: 10px; height: 10px; border-radius: 50%; border: 2px solid #fff; box-shadow: 0 0 0 1px rgba(0,0,0,0.25); }
</style>
</head>
<body>
<div id="map"></div>
<div class="legend">
  <div class="row"><span class="dot" style="background:${PENDING_COLOR}"></span>Needs your review</div>
  <div class="row" style="margin-top:4px"><span class="dot" style="background:${ONGOING_COLOR}"></span>Ongoing</div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
  var pins = ${pinsJson};
  var PENDING = "${PENDING_COLOR}", ONGOING = "${ONGOING_COLOR}";
  // Popup labels below mix free-text client_name/address (typed by tradies
  // and Sales reps, never sanitised upstream) into an HTML string that
  // Leaflet's bindPopup renders as-is — escape before concatenating so a
  // crafted name/address can never inject markup or script into the popup.
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\\"": "&quot;", "'": "&#39;" }[c];
    });
  }
  var map = L.map("map", { zoomControl: true, attributionControl: true });
  // OpenStreetMap tiles — requires an internet connection on device.
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors"
  }).addTo(map);

  if (pins.length === 0) {
    map.setView([${NSW_CENTRE.lat}, ${NSW_CENTRE.lng}], 6);
  } else {
    var bounds = L.latLngBounds([]);
    pins.forEach(function (p) {
      var color = p.category === "pending" ? PENDING : ONGOING;
      var m = L.circleMarker([p.lat, p.lng], {
        radius: p.category === "pending" ? 11 : 9,
        color: "#fff",
        weight: 2,
        fillColor: color,
        fillOpacity: 0.95
      });
      var label = escapeHtml(p.client_name || "Unnamed job") +
        " &middot; " + escapeHtml(p.status.replace(/_/g, " "));
      if (p.total) label += " &middot; $" + escapeHtml(p.total);
      if (p.scheduled_date) label += " &middot; " + escapeHtml(p.scheduled_date);
      if (p.address) label += "<br/><span style=\\"color:#5f6d78\\">" + escapeHtml(p.address) + "</span>";
      m.bindPopup(label, { closeButton: true });
      // One tap on the pin opens that job in the Review screen — the
      // location is already on screen, the next step is the decision.
      m.on("click", function () {
        window.ReactNativeWebView.postMessage(JSON.stringify({ type: "open", quote_id: p.quote_id }));
      });
      m.addTo(map);
      bounds.extend([p.lat, p.lng]);
    });
    map.fitBounds(bounds.pad(0.25));
  }
</script>
</body>
</html>`;
}

export default function OwnerMapScreen() {
  const navigation = useNavigation<Nav>();
  const [data, setData] = useState<OwnerMapResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getOwnerMap());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load the job map.");
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  const pins = data?.pins ?? [];

  return (
    <View style={shared.screen}>
      <View style={{ padding: 20, paddingBottom: 8, gap: 4 }}>
        <Text style={shared.h1}>Maps</Text>
        <Text style={shared.muted}>
          {pins.length} pinpointed
          {data && data.unmapped > 0 ? ` · ${data.unmapped} without a resolvable address` : ""}
        </Text>
      </View>

      <View style={{ flex: 1, marginHorizontal: 0, backgroundColor: colors.line }}>
        {loading ? (
          <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
            <ActivityIndicator size="large" color={colors.accent} />
            <Text style={[shared.muted, { marginTop: 8 }]}>Pinpointing job locations…</Text>
          </View>
        ) : error ? (
          <View style={{ flex: 1, alignItems: "center", justifyContent: "center", padding: 24 }}>
            <Text style={shared.errorText}>{error}</Text>
            <TouchableOpacity style={[shared.buttonSecondary, { marginTop: 16, paddingHorizontal: 24 }]} onPress={load}>
              <Text style={shared.buttonSecondaryText}>Retry</Text>
            </TouchableOpacity>
          </View>
        ) : pins.length === 0 ? (
          <View style={{ flex: 1, alignItems: "center", justifyContent: "center", padding: 24 }}>
            <Text style={shared.muted}>No in-flight jobs have a pinpointed location yet.</Text>
            {data && data.unmapped > 0 ? (
              <Text style={[shared.muted, { marginTop: 4 }]}>
                {data.unmapped} job(s) waiting on an address.
              </Text>
            ) : null}
          </View>
        ) : (
          <WebView
            source={{ html: mapHtml(pins) }}
            style={{ flex: 1, backgroundColor: colors.paper }}
            originWhitelist={["*"]}
            javaScriptEnabled
            onMessage={(e) => {
              try {
                const msg = JSON.parse(e.nativeEvent.data);
                if (msg?.type === "open" && msg.quote_id) {
                  navigation.navigate("OwnerQuoteReview", { quoteId: msg.quote_id });
                }
              } catch {
                /* ignore malformed messages */
              }
            }}
          />
        )}
      </View>
    </View>
  );
}