import { useNavigation, useRoute, RouteProp } from "@react-navigation/native";
import { NativeStackNavigationProp } from "@react-navigation/native-stack";
import React, { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, Text, TouchableOpacity, View } from "react-native";

import { getMyQuote } from "../api/quotes";
import { PRODUCT_TYPE_LABELS, WorkerQuoteDetail } from "../api/types";
import { useDraft } from "../draft/DraftContext";
import { RootStackParamList } from "../navigation/types";
import { colors, shared } from "../theme";

type Nav = NativeStackNavigationProp<RootStackParamList, "QuoteDetail">;
type Rt = RouteProp<RootStackParamList, "QuoteDetail">;

const STATUS_LABELS: Record<string, string> = {
  draft: "In progress",
  extracted: "Processing",
  pending_approval: "Awaiting office approval",
  approved: "Approved",
  rejected: "Rejected",
  needs_manual: "Needs manual review",
  changes_requested: "Changes requested — needs a fix",
};

// Read-only view for a quote once it's left draft state — tapped from
// JobListScreen for any non-draft job. Mostly not editable: once submitted,
// the worker-app mutation endpoints reject changes UNLESS the office sent
// it back (changes_requested), in which case "Fix This Job" below resumes
// editing exactly like a draft (see app/api/worker_quotes.py's
// _get_owned_editable_quote).
export default function QuoteDetailScreen() {
  const navigation = useNavigation<Nav>();
  const { params } = useRoute<Rt>();
  const { hydrateFromServer } = useDraft();

  const [detail, setDetail] = useState<WorkerQuoteDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getMyQuote(params.quoteId)
      .then(setDetail)
      .catch(() => setError("Couldn't load this job — try again."));
  }, [params.quoteId]);

  const onFixThisJob = () => {
    if (!detail) return;
    hydrateFromServer(detail);
    navigation.navigate("Items", { quoteId: detail.quote_id });
  };

  if (error) {
    return (
      <View style={[shared.screen, { justifyContent: "center", padding: 24 }]}>
        <Text style={shared.errorText}>{error}</Text>
      </View>
    );
  }

  if (!detail) {
    return (
      <View style={[shared.screen, { justifyContent: "center" }]}>
        <ActivityIndicator />
      </View>
    );
  }

  return (
    <ScrollView style={shared.screen} contentContainerStyle={shared.scrollContent}>
      <Text style={shared.h1}>{detail.client_name ?? "Unnamed job"}</Text>
      <Text style={shared.muted}>{(STATUS_LABELS[detail.status] ?? detail.status).toUpperCase()}</Text>

      {detail.total && (
        <View style={shared.card}>
          <Text style={shared.h2}>Total</Text>
          <Text style={{ fontSize: 22, fontWeight: "700", color: colors.accent }}>${detail.total}</Text>
        </View>
      )}

      {detail.flags.length > 0 && (
        <View style={shared.card}>
          <Text style={shared.h2}>Flags for the office</Text>
          {detail.flags.map((flag, i) => (
            <Text key={i} style={shared.muted}>
              • {flag.message}
            </Text>
          ))}
        </View>
      )}

      {detail.comments.length > 0 && (
        <View style={shared.card}>
          <Text style={shared.h2}>Office Comments</Text>
          {detail.comments.map((comment) => (
            <View key={comment.id} style={{ gap: 2 }}>
              <Text style={{ fontWeight: "700", color: colors.ink, fontSize: 13 }}>
                {comment.author === "owner" ? "Office" : "You"}
                {comment.action ? ` · ${comment.action.replace("_", " ")}` : ""}
              </Text>
              <Text style={shared.muted}>{comment.body}</Text>
            </View>
          ))}
        </View>
      )}

      {detail.status === "changes_requested" && (
        <TouchableOpacity style={shared.button} onPress={onFixThisJob}>
          <Text style={shared.buttonText}>Fix This Job</Text>
        </TouchableOpacity>
      )}

      <View style={{ gap: 10 }}>
        <Text style={shared.h2}>Items</Text>
        {detail.items.map((item) => (
          <View key={item.item_id} style={shared.card}>
            <Text style={{ fontWeight: "700", color: colors.ink }}>
              Item {item.item_no}: {PRODUCT_TYPE_LABELS[item.product_type]}
            </Text>
            <Text style={shared.muted}>
              {item.material} · {item.room ?? "room not set"}
              {item.width_mm && item.height_mm ? ` · ${item.width_mm} × ${item.height_mm} mm` : ""}
            </Text>
            {item.line_total && <Text style={shared.muted}>${item.line_total}</Text>}
          </View>
        ))}
      </View>
    </ScrollView>
  );
}
