import React from "react";
import { Text, View } from "react-native";

import { colors } from "../theme";

// Higher = less of Anthony's time needed — see
// app/engine/flags.py::compute_readiness_score. Thresholds mirror nothing
// on the backend (the score itself is the source of truth); these just
// pick display tiers.
function tier(score: number): { label: string; color: string; soft: string } {
  if (score >= 80) return { label: "Quick review", color: colors.accent, soft: colors.accentSoft };
  if (score >= 50) return { label: "Some checking needed", color: colors.warn, soft: colors.warnSoft };
  return { label: "Needs your attention", color: colors.danger, soft: colors.dangerSoft };
}

export default function ReadinessBadge({ score, compact = false }: { score: number | null; compact?: boolean }) {
  if (score == null) return null;
  const { label, color, soft } = tier(score);

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 6,
        paddingHorizontal: 8,
        paddingVertical: 3,
        borderRadius: 10,
        backgroundColor: soft,
        alignSelf: "flex-start",
      }}
    >
      <Text style={{ fontSize: 11, fontWeight: "700", color }}>{score}</Text>
      {!compact && <Text style={{ fontSize: 11, fontWeight: "700", color }}>{label.toUpperCase()}</Text>}
    </View>
  );
}
