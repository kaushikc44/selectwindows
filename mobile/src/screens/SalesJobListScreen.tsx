import { useFocusEffect, useNavigation } from "@react-navigation/native";
import { NativeStackNavigationProp } from "@react-navigation/native-stack";
import React, { useCallback, useState } from "react";
import { ActivityIndicator, FlatList, RefreshControl, Text, TouchableOpacity, View } from "react-native";

import { listSalesJobs, SalesJobSummary } from "../api/sales";
import { useAuth } from "../auth/AuthContext";
import { RootStackParamList } from "../navigation/types";
import { colors, shared } from "../theme";

type Nav = NativeStackNavigationProp<RootStackParamList, "SalesJobList">;

const STATUS_LABELS: Record<string, string> = {
  scheduled: "Scheduled",
  draft: "In progress on site",
  extracted: "Processing",
  pending_approval: "Awaiting office approval",
  approved: "Approved",
  rejected: "Rejected",
  needs_manual: "Needs manual review",
  changes_requested: "Changes requested",
  missed: "Missed visit",
};

const WARN_STATUSES = new Set(["missed"]);

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

export default function SalesJobListScreen() {
  const navigation = useNavigation<Nav>();
  const { logout } = useAuth();

  const [jobs, setJobs] = useState<SalesJobSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setJobs(await listSalesJobs());
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

  return (
    <View style={shared.screen}>
      <View style={{ padding: 20, gap: 4 }}>
        <Text style={shared.h1}>Job Schedule</Text>
      </View>

      <FlatList
        data={jobs}
        keyExtractor={(j) => j.quote_id}
        contentContainerStyle={{ paddingHorizontal: 20, gap: 10, paddingBottom: 20 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}
        ListEmptyComponent={
          !loading ? (
            <View style={shared.card}>
              <Text style={shared.muted}>No jobs scheduled yet — tap "+ New Job" to create one.</Text>
            </View>
          ) : null
        }
        renderItem={({ item }) => (
          <TouchableOpacity
            style={shared.card}
            onPress={() => navigation.navigate("SalesJobDetail", { quoteId: item.quote_id })}
          >
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
              <Text style={{ fontWeight: "700", color: colors.ink }}>{item.client_name ?? "Unnamed job"}</Text>
              <StatusBadge status={item.status} />
            </View>
            <Text style={shared.muted}>
              {item.assigned_tradie_name ?? "Unassigned"}
              {item.scheduled_date ? ` · ${item.scheduled_date}` : ""}
            </Text>
          </TouchableOpacity>
        )}
      />

      <View style={{ padding: 20, gap: 10 }}>
        <TouchableOpacity style={shared.button} onPress={() => navigation.navigate("NewSalesJob")}>
          <Text style={shared.buttonText}>+ New Job</Text>
        </TouchableOpacity>
        <TouchableOpacity style={shared.buttonSecondary} onPress={logout}>
          <Text style={shared.buttonSecondaryText}>Log Out</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}
