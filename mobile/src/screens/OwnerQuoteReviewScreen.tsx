import { useFocusEffect, useNavigation, useRoute, RouteProp } from "@react-navigation/native";
import { NativeStackNavigationProp } from "@react-navigation/native-stack";
import React, { useCallback, useState } from "react";
import { ActivityIndicator, ScrollView, Text, TextInput, TouchableOpacity, View } from "react-native";

import { ApiError } from "../api/client";
import { CommentAction, getOwnerQuote, postComment } from "../api/owner";
import { OwnerQuoteDetail, PRODUCT_TYPE_LABELS } from "../api/types";
import ReadinessBadge from "../components/ReadinessBadge";
import { RootStackParamList } from "../navigation/types";
import { colors, shared } from "../theme";

type Nav = NativeStackNavigationProp<RootStackParamList, "OwnerQuoteReview">;
type Rt = RouteProp<RootStackParamList, "OwnerQuoteReview">;

const ACTIONABLE = new Set(["pending_approval", "needs_manual"]);
// An auto-approved quote (approved without Anthony clicking Approve — see
// app/workers/pipeline.py::_auto_approve) can still be undone: he can send it
// back or reject it. Approve is not offered (it would be a no-op).
const UNDOABLE = new Set(["approved"]);

function authorLabel(author: string): string {
  if (author === "owner") return "You";
  if (author === "system") return "AI System";
  return "Tradie";
}

export default function OwnerQuoteReviewScreen() {
  const navigation = useNavigation<Nav>();
  const { params } = useRoute<Rt>();

  const [detail, setDetail] = useState<OwnerQuoteDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [body, setBody] = useState("");
  const [submittingAction, setSubmittingAction] = useState<CommentAction | null>(null);

  const load = () => {
    getOwnerQuote(params.quoteId)
      .then(setDetail)
      .catch(() => setError("Couldn't load this job — try again."));
  };

  // useFocusEffect (not a plain mount-only useEffect) so returning from
  // OwnerEditQuoteScreen re-fetches — this screen stays mounted underneath
  // when Edit is pushed, so a plain effect would never see the changes.
  useFocusEffect(
    useCallback(() => {
      load();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [params.quoteId])
  );

  const onAction = async (action: CommentAction) => {
    if (action !== "comment" && !body.trim()) {
      setError("Add a note explaining why before approving, rejecting, or sending it back.");
      return;
    }
    setError(null);
    setSubmittingAction(action);
    try {
      await postComment(params.quoteId, body.trim() || "(no note)", action);
      setBody("");
      if (action === "comment") {
        load();
      } else {
        navigation.goBack();
      }
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Couldn't send that — try again.");
    } finally {
      setSubmittingAction(null);
    }
  };

  if (error && !detail) {
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

  const actionable = ACTIONABLE.has(detail.status);
  const undoable = UNDOABLE.has(detail.status);

  return (
    <ScrollView style={shared.screen} contentContainerStyle={shared.scrollContent}>
      <Text style={shared.h1}>{detail.client_name ?? "Unnamed job"}</Text>
      <Text style={shared.muted}>
        {detail.tradie_name ?? "Unknown tradie"} · {detail.status.replace("_", " ").toUpperCase()}
      </Text>
      <ReadinessBadge score={detail.readiness_score} />

      {actionable && (
        <TouchableOpacity
          style={shared.buttonSecondary}
          onPress={() => navigation.navigate("OwnerEditQuote", { quoteId: params.quoteId })}
        >
          <Text style={shared.buttonSecondaryText}>Edit Quote</Text>
        </TouchableOpacity>
      )}

      <TouchableOpacity
        style={shared.buttonSecondary}
        onPress={() => navigation.navigate("OwnerAiLogs", { quoteId: params.quoteId })}
      >
        <Text style={shared.buttonSecondaryText}>AI activity on this job</Text>
      </TouchableOpacity>

      <View style={shared.card}>
        <Text style={shared.h2}>Customer &amp; Site</Text>
        {detail.header.phone && <Text style={shared.muted}>Phone: {detail.header.phone}</Text>}
        {detail.header.email && <Text style={shared.muted}>Email: {detail.header.email}</Text>}
        {detail.header.client_address && <Text style={shared.muted}>Site: {detail.header.client_address}</Text>}
        {detail.header.delivery_address && detail.header.delivery_address !== detail.header.client_address && (
          <Text style={shared.muted}>Delivery: {detail.header.delivery_address}</Text>
        )}
        {detail.header.job_no && <Text style={shared.muted}>Job #: {detail.header.job_no}</Text>}
        {detail.header.rep && <Text style={shared.muted}>Rep: {detail.header.rep}</Text>}
        {detail.header.colour && <Text style={shared.muted}>Colour: {detail.header.colour}</Text>}
        {detail.header.glass && <Text style={shared.muted}>Glass: {detail.header.glass}</Text>}
        {(detail.header.wind_rating || detail.header.water_rating) && (
          <Text style={shared.muted}>
            Wind/Water rating: {detail.header.wind_rating ?? "unmarked"} / {detail.header.water_rating ?? "unmarked"}
          </Text>
        )}
      </View>

      <View style={shared.card}>
        <Text style={shared.h2}>Installation</Text>
        {detail.installation.building_type && (
          <Text style={shared.muted}>Building: {detail.installation.building_type}</Text>
        )}
        {detail.installation.construction && (
          <Text style={shared.muted}>Construction: {detail.installation.construction}</Text>
        )}
        {detail.installation.floor_level && <Text style={shared.muted}>Floor: {detail.installation.floor_level}</Text>}
        {detail.installation.remove_existing && (
          <Text style={shared.muted}>Removing: {detail.installation.remove_existing}</Text>
        )}
        {detail.installation.brick_removal_m2 != null && (
          <Text style={shared.muted}>Brick removal: {detail.installation.brick_removal_m2} m²</Text>
        )}
        {(detail.installation.scaffold === "yes" ||
          detail.installation.hoist === "yes" ||
          detail.installation.brick_saw === "yes") && (
          <Text style={shared.muted}>
            Equipment:{" "}
            {[
              detail.installation.scaffold === "yes" && "scaffold",
              detail.installation.hoist === "yes" && "hoist",
              detail.installation.brick_saw === "yes" && "brick saw",
            ]
              .filter(Boolean)
              .join(", ")}
          </Text>
        )}
        {detail.installation.asbestos === "yes" && (
          <Text style={shared.errorText}>Asbestos present — SELECT WILL NOT REMOVE</Text>
        )}
        {detail.installation.notes && <Text style={shared.muted}>Notes: {detail.installation.notes}</Text>}
        {!detail.installation.building_type &&
          !detail.installation.construction &&
          !detail.installation.notes && <Text style={shared.muted}>No installation detail supplied.</Text>}
      </View>

      <View style={shared.card}>
        <Text style={shared.h2}>Pricing Breakdown</Text>
        {detail.items_subtotal && <Text style={shared.muted}>Items subtotal: ${detail.items_subtotal}</Text>}
        {detail.installation_subtotal && (
          <Text style={shared.muted}>Installation subtotal: ${detail.installation_subtotal}</Text>
        )}
        {detail.gst_amount && <Text style={shared.muted}>GST: ${detail.gst_amount}</Text>}
        {detail.total && (
          <Text style={{ fontSize: 22, fontWeight: "700", color: colors.accent }}>Total: ${detail.total}</Text>
        )}
      </View>

      {detail.agent_notes.length > 0 && (
        <View style={[shared.card, { borderColor: colors.accent }]}>
          <Text style={shared.h2}>Agent Notes</Text>
          <Text style={shared.muted}>Matches something you've corrected before — worth a second look.</Text>
          {detail.agent_notes.map((note, i) => (
            <Text key={i} style={{ color: colors.ink }}>
              • {note}
            </Text>
          ))}
        </View>
      )}

      {detail.flags.length > 0 && (
        <View style={shared.card}>
          <Text style={shared.h2}>Flags</Text>
          {detail.flags.map((flag, i) => (
            <Text key={i} style={shared.muted}>
              • {flag.message}
            </Text>
          ))}
        </View>
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
              {item.sill_height_mm ? ` · sill ${item.sill_height_mm} mm` : ""}
            </Text>
            <Text style={shared.muted}>
              Qty {item.qty}
              {item.unit_price ? ` · $${item.unit_price} each` : ""}
              {item.line_total ? ` · $${item.line_total} total` : ""}
            </Text>
            {item.glass_spec && <Text style={shared.muted}>Glass: {item.glass_spec}</Text>}
            {item.frame_components.length > 0 && (
              <Text style={shared.muted}>Frame: {item.frame_components.join(", ")}</Text>
            )}
            {item.hardware.length > 0 && <Text style={shared.muted}>Hardware: {item.hardware.join(", ")}</Text>}
            {item.sealant_and_fixings.length > 0 && (
              <Text style={shared.muted}>Sealant &amp; fixings: {item.sealant_and_fixings.join(", ")}</Text>
            )}
            {item.enrichment_notes && <Text style={shared.muted}>Note: {item.enrichment_notes}</Text>}
          </View>
        ))}
      </View>

      {detail.comments.length > 0 && (
        <View style={shared.card}>
          <Text style={shared.h2}>Comment Thread</Text>
          {detail.comments.map((comment) => (
            <View key={comment.id} style={{ gap: 2 }}>
              <Text style={{ fontWeight: "700", color: colors.ink, fontSize: 13 }}>
                {authorLabel(comment.author)}
                {comment.action ? ` · ${comment.action.replace("_", " ")}` : ""}
              </Text>
              <Text style={shared.muted}>{comment.body}</Text>
            </View>
          ))}
        </View>
      )}

      <View style={shared.card}>
        <Text style={shared.h2}>{actionable ? "Your Review" : undoable ? "Undo Auto-Approval" : "Add a Comment"}</Text>
        {undoable && (
          <Text style={shared.muted}>
            The AI approval system approved this quote on your behalf. Send it back or reject it to undo.
          </Text>
        )}
        <TextInput
          style={[shared.input, { minHeight: 70, textAlignVertical: "top" }]}
          value={body}
          onChangeText={setBody}
          multiline
          placeholder={actionable || undoable ? "e.g. Needs safety glass for the low sill" : "Add a note"}
        />
        {error && <Text style={shared.errorText}>{error}</Text>}

        {actionable ? (
          <View style={{ gap: 8 }}>
            <TouchableOpacity
              style={shared.button}
              onPress={() => onAction("approve")}
              disabled={submittingAction !== null}
            >
              {submittingAction === "approve" ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={shared.buttonText}>Approve</Text>
              )}
            </TouchableOpacity>
            <TouchableOpacity
              style={shared.buttonSecondary}
              onPress={() => onAction("request_changes")}
              disabled={submittingAction !== null}
            >
              {submittingAction === "request_changes" ? (
                <ActivityIndicator />
              ) : (
                <Text style={shared.buttonSecondaryText}>Send Back for Changes</Text>
              )}
            </TouchableOpacity>
            <TouchableOpacity
              style={[shared.buttonSecondary, { borderColor: colors.danger }]}
              onPress={() => onAction("reject")}
              disabled={submittingAction !== null}
            >
              {submittingAction === "reject" ? (
                <ActivityIndicator color={colors.danger} />
              ) : (
                <Text style={[shared.buttonSecondaryText, { color: colors.danger }]}>Reject</Text>
              )}
            </TouchableOpacity>
          </View>
        ) : undoable ? (
          <View style={{ gap: 8 }}>
            <TouchableOpacity
              style={shared.buttonSecondary}
              onPress={() => onAction("request_changes")}
              disabled={submittingAction !== null}
            >
              {submittingAction === "request_changes" ? (
                <ActivityIndicator />
              ) : (
                <Text style={shared.buttonSecondaryText}>Send Back for Changes</Text>
              )}
            </TouchableOpacity>
            <TouchableOpacity
              style={[shared.buttonSecondary, { borderColor: colors.danger }]}
              onPress={() => onAction("reject")}
              disabled={submittingAction !== null}
            >
              {submittingAction === "reject" ? (
                <ActivityIndicator color={colors.danger} />
              ) : (
                <Text style={[shared.buttonSecondaryText, { color: colors.danger }]}>Reject</Text>
              )}
            </TouchableOpacity>
          </View>
        ) : (
          <TouchableOpacity
            style={shared.buttonSecondary}
            onPress={() => onAction("comment")}
            disabled={submittingAction !== null}
          >
            {submittingAction === "comment" ? (
              <ActivityIndicator />
            ) : (
              <Text style={shared.buttonSecondaryText}>Add Comment</Text>
            )}
          </TouchableOpacity>
        )}
      </View>
    </ScrollView>
  );
}
