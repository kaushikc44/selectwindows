import { useNavigation, useRoute, RouteProp } from "@react-navigation/native";
import { NativeStackNavigationProp } from "@react-navigation/native-stack";
import React, { useState } from "react";
import { ActivityIndicator, ScrollView, Text, TextInput, TouchableOpacity, View } from "react-native";

import { ApiError } from "../api/client";
import { addItem } from "../api/quotes";
import { Material, MATERIALS, ProductType, ROOMS, YES_NO_UNMARKED } from "../api/types";
import ChipPicker from "../components/ChipPicker";
import ConfigCodePicker, { ConfigCodeResult } from "../components/ConfigCodePicker";
import { useDraft } from "../draft/DraftContext";
import { RootStackParamList } from "../navigation/types";
import { shared } from "../theme";

type Nav = NativeStackNavigationProp<RootStackParamList, "AddItem">;
type Rt = RouteProp<RootStackParamList, "AddItem">;

export default function AddItemScreen() {
  const navigation = useNavigation<Nav>();
  const { params } = useRoute<Rt>();
  const { addItem: addItemToDraft } = useDraft();

  // Product type is derived from the config picker, not asked for
  // separately — a config code always implies exactly one ProductType on
  // the backend (see app/engine/config_codes.py), so asking twice would
  // only create a way for the two to disagree.
  const [config, setConfig] = useState<ConfigCodeResult | null>(null);
  const [material, setMaterial] = useState<Material | null>(null);
  const [room, setRoom] = useState<string | null>(null);
  const [screen, setScreen] = useState<(typeof YES_NO_UNMARKED)[number]>("unmarked");
  const [sillHeight, setSillHeight] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSave = async () => {
    if (!config || !material) {
      setError("Configuration and material are required.");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const productType = config.productType as ProductType;
      const result = await addItem(params.quoteId, {
        product_type: productType,
        material,
        room,
        screen,
        config_code: config.code,
        sill_height_mm: sillHeight.trim() ? parseInt(sillHeight, 10) : null,
      });
      addItemToDraft({
        item_id: result.item_id,
        item_no: result.item_no,
        product_type: productType,
        material,
        room,
        width_mm: null,
        height_mm: null,
      });
      navigation.replace("Capture", {
        quoteId: params.quoteId,
        itemId: result.item_id,
        itemLabel: `Item ${result.item_no}: ${config.code}`,
      });
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Couldn't add the item — try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ScrollView style={shared.screen} contentContainerStyle={shared.scrollContent}>
      <Text style={shared.h1}>Add Item</Text>
      <Text style={shared.muted}>
        Replaces the paper form's hand-drawn configuration grid — tap the type instead of sketching it.
      </Text>

      <View style={shared.card}>
        <Text style={shared.h2}>Configuration</Text>
        <ConfigCodePicker onChange={setConfig} />
        {config && <Text style={[shared.muted, { fontFamily: "Courier" }]}>Code: {config.code}</Text>}
      </View>

      <View style={shared.card}>
        <Text style={shared.h2}>Material</Text>
        <ChipPicker options={MATERIALS} value={material} onChange={setMaterial} />
      </View>

      <View style={shared.card}>
        <Text style={shared.h2}>Room</Text>
        <ChipPicker options={ROOMS} value={room} onChange={setRoom} />
      </View>

      <View style={shared.card}>
        <Text style={shared.h2}>Flyscreen</Text>
        <ChipPicker options={YES_NO_UNMARKED} value={screen} onChange={setScreen} />
      </View>

      <View style={shared.card}>
        <Text style={shared.h2}>Sill Height (mm)</Text>
        <Text style={shared.muted}>
          Optional — for doors or windows near the floor. Drives the mandatory AS1288 safety-glass check.
        </Text>
        <TextInput
          style={shared.input}
          value={sillHeight}
          onChangeText={setSillHeight}
          keyboardType="number-pad"
          placeholder="e.g. 400"
        />
      </View>

      {error && <Text style={shared.errorText}>{error}</Text>}

      <TouchableOpacity style={shared.button} onPress={onSave} disabled={submitting}>
        {submitting ? <ActivityIndicator color="#fff" /> : <Text style={shared.buttonText}>Save &amp; Capture Measurements</Text>}
      </TouchableOpacity>
    </ScrollView>
  );
}
