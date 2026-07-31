import { useNavigation } from "@react-navigation/native";
import { NativeStackNavigationProp } from "@react-navigation/native-stack";
import React from "react";
import { FlatList, Text, TouchableOpacity, View } from "react-native";

import { PRODUCT_TYPE_LABELS } from "../api/types";
import { useDraft } from "../draft/DraftContext";
import { RootStackParamList } from "../navigation/types";
import { colors, shared } from "../theme";

type Nav = NativeStackNavigationProp<RootStackParamList, "Items">;

export default function ItemsScreen() {
  const navigation = useNavigation<Nav>();
  const { quoteId, clientName, items, status } = useDraft();
  const isResubmit = status === "changes_requested";

  const readyCount = items.filter((it) => it.width_mm !== null && it.height_mm !== null).length;
  const canSubmit = items.length > 0 && readyCount === items.length;

  return (
    <View style={shared.screen}>
      <View style={{ padding: 20, gap: 4 }}>
        <Text style={shared.h1}>{clientName ?? "Job"}</Text>
        <Text style={shared.muted}>
          {items.length} item{items.length === 1 ? "" : "s"} · {readyCount} measured
        </Text>
      </View>

      <FlatList
        data={items}
        keyExtractor={(item) => item.item_id}
        contentContainerStyle={{ paddingHorizontal: 20, gap: 10, paddingBottom: 20 }}
        ListEmptyComponent={
          <View style={shared.card}>
            <Text style={shared.muted}>No items yet. Tap "Add Item" to add the first window or door.</Text>
          </View>
        }
        renderItem={({ item }) => {
          const done = item.width_mm !== null && item.height_mm !== null;
          return (
            <TouchableOpacity
              style={shared.card}
              onPress={() =>
                navigation.navigate("Capture", {
                  quoteId: quoteId!,
                  itemId: item.item_id,
                  itemLabel: `Item ${item.item_no}: ${PRODUCT_TYPE_LABELS[item.product_type]}`,
                })
              }
            >
              <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                <Text style={{ fontWeight: "700", color: colors.ink }}>
                  Item {item.item_no}: {PRODUCT_TYPE_LABELS[item.product_type]}
                </Text>
                <View
                  style={{
                    paddingHorizontal: 8,
                    paddingVertical: 3,
                    borderRadius: 10,
                    backgroundColor: done ? colors.accentSoft : colors.warnSoft,
                  }}
                >
                  <Text style={{ fontSize: 11, fontWeight: "700", color: done ? colors.accent : colors.warn }}>
                    {done ? "MEASURED" : "NEEDS PHOTOS"}
                  </Text>
                </View>
              </View>
              <Text style={shared.muted}>
                {item.material} · {item.room ?? "room not set"}
                {done ? ` · ${item.width_mm} × ${item.height_mm} mm` : ""}
              </Text>
            </TouchableOpacity>
          );
        }}
      />

      <View style={{ padding: 20, gap: 10 }}>
        <TouchableOpacity style={shared.buttonSecondary} onPress={() => navigation.navigate("AddItem", { quoteId: quoteId! })}>
          <Text style={shared.buttonSecondaryText}>+ Add Item</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[shared.button, !canSubmit && { opacity: 0.4 }]}
          disabled={!canSubmit}
          onPress={() => navigation.navigate("ReviewSubmit", { quoteId: quoteId! })}
        >
          <Text style={shared.buttonText}>{isResubmit ? "Review & Resend" : "Review & Submit"}</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}
