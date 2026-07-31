import { useFocusEffect, useNavigation, useRoute, RouteProp } from "@react-navigation/native";
import { NativeStackNavigationProp } from "@react-navigation/native-stack";
import React, { useCallback, useState } from "react";
import { FlatList, RefreshControl, Text, TouchableOpacity, View } from "react-native";

import { getAiLogs } from "../api/owner";
import { AiLog, AiLogsResponse } from "../api/types";
import { RootStackParamList } from "../navigation/types";
import { colors, shared } from "../theme";

type Nav = NativeStackNavigationProp<RootStackParamList, "OwnerAiLogs">;
type Route = RouteProp<RootStackParamList, "OwnerAiLogs">;

function purposeLabel(purpose: string): string {
  return purpose.replace(/_/g, " ");
}

function LogRow({ log, expanded, onToggle }: { log: AiLog; expanded: boolean; onToggle: () => void }) {
  const tokens = log.prompt_tokens != null || log.completion_tokens != null
    ? `↑${log.prompt_tokens ?? 0} ↓${log.completion_tokens ?? 0}`
    : null;
  return (
    <TouchableOpacity style={shared.card} onPress={onToggle} activeOpacity={0.7}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <Text style={{ fontWeight: "700", color: colors.ink, textTransform: "capitalize", flexShrink: 1 }}>
          {purposeLabel(log.purpose)}
        </Text>
        <View
          style={{
            paddingHorizontal: 8,
            paddingVertical: 3,
            borderRadius: 10,
            backgroundColor: log.success ? colors.accentSoft : colors.dangerSoft,
          }}
        >
          <Text style={{ fontSize: 11, fontWeight: "700", color: log.success ? colors.accent : colors.danger }}>
            {log.success ? "OK" : "FAIL"}
          </Text>
        </View>
      </View>
      <Text style={shared.muted}>
        {log.model}
        {log.latency_ms != null ? ` · ${log.latency_ms}ms` : ""}
        {tokens ? ` · ${tokens}` : ""}
        {" · "}
        {new Date(log.created_at).toLocaleString()}
      </Text>

      {expanded && (
        <View style={{ gap: 8, marginTop: 4 }}>
          {!log.success && log.error ? (
            <View>
              <Text style={shared.h2}>Error</Text>
              <Text style={{ color: colors.danger, fontSize: 12 }}>{log.error}</Text>
            </View>
          ) : null}
          <View>
            <Text style={shared.h2}>Input sent</Text>
            <Text style={{ fontFamily: "Menlo", fontSize: 11, color: colors.ink }}>
              {log.input_text ?? "(none)"}
            </Text>
          </View>
          <View>
            <Text style={shared.h2}>Output</Text>
            <Text style={{ fontFamily: "Menlo", fontSize: 11, color: colors.ink }}>
              {log.output_text ?? "(none)"}
            </Text>
          </View>
        </View>
      )}
    </TouchableOpacity>
  );
}

export default function OwnerAiLogsScreen() {
  const navigation = useNavigation<Nav>();
  const route = useRoute<Route>();
  const quoteId = route.params?.quoteId;
  const [data, setData] = useState<AiLogsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await getAiLogs(quoteId));
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [quoteId]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  const logs = data?.logs ?? [];

  return (
    <View style={shared.screen}>
      <View style={{ padding: 20, gap: 6 }}>
        <Text style={shared.h1}>AI Logs</Text>
        <Text style={shared.muted}>
          {quoteId ? "Scoped to this job" : "Every LLM call across all jobs"} — input sent, output returned, per call.
        </Text>
        {data ? (
          <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap", marginTop: 4 }}>
            <View style={[shared.chip, { borderColor: colors.accent, backgroundColor: colors.accentSoft }]}>
              <Text style={[shared.chipText, { color: colors.accent, fontWeight: "700" }]}>
                {data.total} calls
              </Text>
            </View>
            {data.failures > 0 ? (
              <View style={[shared.chip, { borderColor: colors.danger, backgroundColor: colors.dangerSoft }]}>
                <Text style={[shared.chipText, { color: colors.danger, fontWeight: "700" }]}>
                  {data.failures} failed
                </Text>
              </View>
            ) : null}
            {data.by_purpose.slice(0, 6).map((p) => (
              <View key={p.purpose} style={shared.chip}>
                <Text style={shared.chipText}>
                  {purposeLabel(p.purpose)} · {p.count}
                </Text>
              </View>
            ))}
          </View>
        ) : null}
      </View>

      <FlatList
        data={logs}
        keyExtractor={(l) => l.id}
        contentContainerStyle={{ paddingHorizontal: 20, gap: 10, paddingBottom: 20 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}
        ListEmptyComponent={
          !loading ? (
            <View style={shared.card}>
              <Text style={shared.muted}>
                {quoteId ? "No AI calls logged for this job yet." : "No AI calls logged yet."}
              </Text>
            </View>
          ) : null
        }
        renderItem={({ item }) => (
          <LogRow
            log={item}
            expanded={expanded === item.id}
            onToggle={() => setExpanded((cur) => (cur === item.id ? null : item.id))}
          />
        )}
      />

      {!quoteId ? (
        <View style={{ padding: 20 }}>
          <TouchableOpacity style={shared.buttonSecondary} onPress={() => navigation.goBack()}>
            <Text style={shared.buttonSecondaryText}>Back</Text>
          </TouchableOpacity>
        </View>
      ) : null}
    </View>
  );
}