import { useFocusEffect, useNavigation } from "@react-navigation/native";
import { NativeStackNavigationProp } from "@react-navigation/native-stack";
import React, { useCallback, useState } from "react";
import { ActivityIndicator, FlatList, RefreshControl, Text, TouchableOpacity, View } from "react-native";

import { getMyQuote, listMyQuotes } from "../api/quotes";
import { QuoteSummary } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useDraft } from "../draft/DraftContext";
import { RootStackParamList } from "../navigation/types";
import { colors, shared } from "../theme";

type Nav = NativeStackNavigationProp<RootStackParamList, "JobList">;

const STATUS_LABELS: Record<string, string> = {
  scheduled: "Scheduled — not started",
  draft: "In progress",
  extracted: "Processing",
  pending_approval: "Awaiting office approval",
  approved: "Approved",
  rejected: "Rejected",
  needs_manual: "Needs manual review",
  changes_requested: "Changes requested",
  missed: "Missed — waiting on reschedule",
};

const WARN_STATUSES = new Set(["scheduled", "missed", "changes_requested"]);

function StatusBadge({ status }: { status: string }) {
  const isWarn = WARN_STATUSES.has(status);
  return (
    <View
      style={{
        paddingHorizontal: 8,
        paddingVertical: 3,
        borderRadius: 10,
        backgroundColor: isWarn ? colors.warnSoft : colors.accentSoft,
      }}
    >
      <Text style={{ fontSize: 11, fontWeight: "700", color: isWarn ? colors.warn : colors.accent }}>
        {(STATUS_LABELS[status] ?? status).toUpperCase()}
      </Text>
    </View>
  );
}

export default function JobListScreen() {
  const navigation = useNavigation<Nav>();
  const { logout } = useAuth();
  const { hydrateFromServer, reset } = useDraft();

  const [quotes, setQuotes] = useState<QuoteSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [resumingId, setResumingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setQuotes(await listMyQuotes());
    } catch {
      // Best-effort — an empty list with no error banner is fine here.
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  const onOpenQuote = async (quote: QuoteSummary) => {
    // Every job is created by Sales now (Phase F) — a fresh "scheduled" job
    // hasn't had its property/compliance details filled in yet, so it goes
    // to PropertyDetails first; a "draft" job already has those and jumps
    // straight to Items, as before.
    if (quote.status === "scheduled") {
      reset();
      navigation.navigate("PropertyDetails", { quoteId: quote.quote_id });
      return;
    }
    if (quote.status !== "draft") {
      navigation.navigate("QuoteDetail", { quoteId: quote.quote_id });
      return;
    }
    setResumingId(quote.quote_id);
    try {
      const detail = await getMyQuote(quote.quote_id);
      hydrateFromServer(detail);
      navigation.navigate("Items", { quoteId: quote.quote_id });
    } finally {
      setResumingId(null);
    }
  };

  return (
    <View style={shared.screen}>
      <View style={{ padding: 20, gap: 4 }}>
        <Text style={shared.h1}>Select Windows — Field App</Text>
      </View>

      <FlatList
        data={quotes}
        keyExtractor={(q) => q.quote_id}
        contentContainerStyle={{ paddingHorizontal: 20, gap: 10, paddingBottom: 20 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}
        ListEmptyComponent={
          !loading ? (
            <View style={shared.card}>
              <Text style={shared.muted}>No jobs assigned to you yet.</Text>
            </View>
          ) : null
        }
        renderItem={({ item }) => (
          <TouchableOpacity style={shared.card} onPress={() => onOpenQuote(item)} disabled={resumingId === item.quote_id}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
              <Text style={{ fontWeight: "700", color: colors.ink }}>{item.client_name ?? "Unnamed job"}</Text>
              {resumingId === item.quote_id ? <ActivityIndicator size="small" /> : <StatusBadge status={item.status} />}
            </View>
            <Text style={shared.muted}>
              {item.scheduled_date ? `Visit: ${item.scheduled_date}` : new Date(item.created_at).toLocaleDateString()}
              {item.total ? ` · $${item.total}` : ""}
            </Text>
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
