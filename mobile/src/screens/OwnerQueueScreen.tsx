import { useFocusEffect, useNavigation } from "@react-navigation/native";
import { NativeStackNavigationProp } from "@react-navigation/native-stack";
import React, { useCallback, useState } from "react";
import { FlatList, RefreshControl, Text, TouchableOpacity, View } from "react-native";

import { listOwnerQueue } from "../api/owner";
import { OwnerQuoteSummary } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import ReadinessBadge from "../components/ReadinessBadge";
import { RootStackParamList } from "../navigation/types";
import { colors, shared } from "../theme";

type Nav = NativeStackNavigationProp<RootStackParamList, "OwnerQueue">;

const STATUS_LABELS: Record<string, string> = {
  pending_approval: "Awaiting your review",
  needs_manual: "Needs manual review",
  changes_requested: "Sent back — waiting on tradie",
  approved: "Approved",
  rejected: "Rejected",
};

const ACTIONABLE = new Set(["pending_approval", "needs_manual"]);

function StatusBadge({ status }: { status: string }) {
  const actionable = ACTIONABLE.has(status);
  return (
    <View
      style={{
        paddingHorizontal: 8,
        paddingVertical: 3,
        borderRadius: 10,
        backgroundColor: actionable ? colors.warnSoft : colors.accentSoft,
      }}
    >
      <Text style={{ fontSize: 11, fontWeight: "700", color: actionable ? colors.warn : colors.accent }}>
        {(STATUS_LABELS[status] ?? status).toUpperCase()}
      </Text>
    </View>
  );
}

export default function OwnerQueueScreen() {
  const navigation = useNavigation<Nav>();
  const { logout } = useAuth();

  const [quotes, setQuotes] = useState<OwnerQuoteSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setQuotes(await listOwnerQueue());
    } catch {
      // Best-effort — an empty queue with no error banner is fine here.
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  return (
    <View style={shared.screen}>
      <View style={{ padding: 20, gap: 4 }}>
        <Text style={shared.h1}>Review Queue</Text>
      </View>

      <FlatList
        data={quotes}
        keyExtractor={(q) => q.quote_id}
        contentContainerStyle={{ paddingHorizontal: 20, gap: 10, paddingBottom: 20 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}
        ListEmptyComponent={
          !loading ? (
            <View style={shared.card}>
              <Text style={shared.muted}>Nothing waiting on you right now.</Text>
            </View>
          ) : null
        }
        renderItem={({ item }) => (
          <TouchableOpacity
            style={shared.card}
            onPress={() => navigation.navigate("OwnerQuoteReview", { quoteId: item.quote_id })}
          >
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
              <Text style={{ fontWeight: "700", color: colors.ink }}>{item.client_name ?? "Unnamed job"}</Text>
              <StatusBadge status={item.status} />
            </View>
            <Text style={shared.muted}>
              {item.tradie_name ?? "Unknown tradie"} · {new Date(item.created_at).toLocaleDateString()}
              {item.total ? ` · $${item.total}` : ""}
            </Text>
            <ReadinessBadge score={item.readiness_score} compact />
          </TouchableOpacity>
        )}
      />

      <View style={{ padding: 20 }}>
        <TouchableOpacity style={shared.buttonSecondary} onPress={logout}>
          <Text style={shared.buttonSecondaryText}>Log Out</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}
