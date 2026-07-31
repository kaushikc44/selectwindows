import { useNavigation, useRoute, RouteProp } from "@react-navigation/native";
import { NativeStackNavigationProp } from "@react-navigation/native-stack";
import React, { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, Text, TextInput, TouchableOpacity, View } from "react-native";

import { ApiError } from "../api/client";
import { editQuote, getOwnerQuote, OwnerItemEditInput } from "../api/owner";
import {
  EMPTY_REVEAL,
  MATERIALS,
  Material,
  OwnerQuoteDetail,
  PRODUCT_TYPES,
  PRODUCT_TYPE_LABELS,
  ProductType,
  RevealLining,
  ROOMS,
  WATER_RATINGS,
  WIND_RATINGS,
  YES_NO_UNMARKED,
} from "../api/types";
import AddressAutocomplete from "../components/AddressAutocomplete";
import ChipPicker from "../components/ChipPicker";
import { RootStackParamList } from "../navigation/types";
import { colors, shared } from "../theme";

type Nav = NativeStackNavigationProp<RootStackParamList, "OwnerEditQuote">;
type Rt = RouteProp<RootStackParamList, "OwnerEditQuote">;

const GLASS_OPTIONS = ["single", "double_glazed", "acoustic", "toughened", "BAL40_pyro"] as const;
const BUILDING_TYPES = ["Residence", "Unit", "Strata", "Other"] as const;
const CONSTRUCTIONS = ["Timber Frame", "B. Veneer", "Cavity Brick", "Other"] as const;
const FLOOR_LEVELS = ["Ground", "1st", "2nd", "3rd"] as const;
const REMOVE_EXISTING = ["Timber", "Aluminium", "Steel", "Prep Openings"] as const;
const SPECIES = ["maple", "pine", "unmarked"] as const;
const DEFINS = ["80", "100", "116", "138", "165", "other", "unmarked"] as const;

function RevealLiningPicker({
  title,
  value,
  onChange,
}: {
  title: string;
  value: RevealLining;
  onChange: (next: RevealLining) => void;
}) {
  return (
    <View style={{ gap: 8 }}>
      <TouchableOpacity
        style={{ flexDirection: "row", alignItems: "center", gap: 8 }}
        onPress={() => onChange({ ...value, selected: !value.selected })}
      >
        <View
          style={{
            width: 20,
            height: 20,
            borderRadius: 4,
            borderWidth: 1.5,
            borderColor: colors.accent,
            backgroundColor: value.selected ? colors.accent : "transparent",
          }}
        />
        <Text style={shared.muted}>{title}</Text>
      </TouchableOpacity>
      {value.selected && (
        <>
          <ChipPicker options={SPECIES} value={value.species} onChange={(species) => onChange({ ...value, species })} />
          <ChipPicker options={DEFINS} value={value.defin} onChange={(defin) => onChange({ ...value, defin })} />
        </>
      )}
    </View>
  );
}

// Local editable-item shape — a superset of OwnerItemEditInput that keeps
// the materials list fields as plain comma-separated text while typing,
// only split into arrays right before the API call.
interface EditableItem {
  item_id: string | null;
  delete: boolean;
  product_type: ProductType;
  material: Material;
  room: string | null;
  config_code: string;
  qty: string;
  width_mm: string;
  height_mm: string;
  sill_height_mm: string;
  glass_spec: string;
  hardware: string;
  frame_components: string;
  sealant_and_fixings: string;
  enrichment_notes: string;
}

function blankItem(): EditableItem {
  return {
    item_id: null,
    delete: false,
    product_type: "awning",
    material: "aluminium",
    room: null,
    config_code: "",
    qty: "1",
    width_mm: "",
    height_mm: "",
    sill_height_mm: "",
    glass_spec: "",
    hardware: "",
    frame_components: "",
    sealant_and_fixings: "",
    enrichment_notes: "",
  };
}

function ItemEditCard({
  item,
  index,
  onChange,
  onRemove,
}: {
  item: EditableItem;
  index: number;
  onChange: (next: EditableItem) => void;
  onRemove: () => void;
}) {
  const set = <K extends keyof EditableItem>(key: K, value: EditableItem[K]) => onChange({ ...item, [key]: value });

  return (
    <View style={shared.card}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <Text style={shared.h2}>Item {index + 1}</Text>
        <TouchableOpacity onPress={onRemove}>
          <Text style={[shared.errorText, { fontWeight: "700" }]}>Remove</Text>
        </TouchableOpacity>
      </View>

      <View>
        <Text style={shared.label}>Product type</Text>
        <ChipPicker
          options={PRODUCT_TYPES.map((p) => ({ value: p, label: PRODUCT_TYPE_LABELS[p] }))}
          value={item.product_type}
          onChange={(v) => set("product_type", v)}
        />
      </View>
      <View>
        <Text style={shared.label}>Material</Text>
        <ChipPicker options={MATERIALS} value={item.material} onChange={(v) => set("material", v)} />
      </View>
      <View>
        <Text style={shared.label}>Room</Text>
        <ChipPicker options={ROOMS} value={item.room} onChange={(v) => set("room", v)} />
      </View>
      <View>
        <Text style={shared.label}>Config code (advanced, optional)</Text>
        <TextInput
          style={shared.input}
          value={item.config_code}
          onChangeText={(v) => set("config_code", v)}
          autoCapitalize="characters"
        />
      </View>

      <View style={shared.row}>
        <View style={{ flex: 1 }}>
          <Text style={shared.label}>Width (mm)</Text>
          <TextInput style={shared.input} value={item.width_mm} onChangeText={(v) => set("width_mm", v)} keyboardType="number-pad" />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={shared.label}>Height (mm)</Text>
          <TextInput style={shared.input} value={item.height_mm} onChangeText={(v) => set("height_mm", v)} keyboardType="number-pad" />
        </View>
      </View>
      <View style={shared.row}>
        <View style={{ flex: 1 }}>
          <Text style={shared.label}>Qty</Text>
          <TextInput style={shared.input} value={item.qty} onChangeText={(v) => set("qty", v)} keyboardType="number-pad" />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={shared.label}>Sill height (mm)</Text>
          <TextInput
            style={shared.input}
            value={item.sill_height_mm}
            onChangeText={(v) => set("sill_height_mm", v)}
            keyboardType="number-pad"
          />
        </View>
      </View>

      <Text style={shared.h2}>Materials Spec</Text>
      <Text style={shared.muted}>
        Overrides the AI estimate directly — your entry here is treated as verified, no "unreviewed" flag.
      </Text>
      <View>
        <Text style={shared.label}>Glass</Text>
        <TextInput style={shared.input} value={item.glass_spec} onChangeText={(v) => set("glass_spec", v)} />
      </View>
      <View>
        <Text style={shared.label}>Hardware (comma-separated)</Text>
        <TextInput style={shared.input} value={item.hardware} onChangeText={(v) => set("hardware", v)} />
      </View>
      <View>
        <Text style={shared.label}>Frame components (comma-separated)</Text>
        <TextInput style={shared.input} value={item.frame_components} onChangeText={(v) => set("frame_components", v)} />
      </View>
      <View>
        <Text style={shared.label}>Sealant &amp; fixings (comma-separated)</Text>
        <TextInput
          style={shared.input}
          value={item.sealant_and_fixings}
          onChangeText={(v) => set("sealant_and_fixings", v)}
        />
      </View>
      <View>
        <Text style={shared.label}>Notes</Text>
        <TextInput style={shared.input} value={item.enrichment_notes} onChangeText={(v) => set("enrichment_notes", v)} />
      </View>
    </View>
  );
}

export default function OwnerEditQuoteScreen() {
  const navigation = useNavigation<Nav>();
  const { params } = useRoute<Rt>();

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [clientName, setClientName] = useState("");
  const [clientAddress, setClientAddress] = useState("");
  const [contactName, setContactName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [jobNo, setJobNo] = useState("");

  const [colour, setColour] = useState("");
  const [glass, setGlass] = useState<(typeof GLASS_OPTIONS)[number] | null>(null);
  const [windRating, setWindRating] = useState<(typeof WIND_RATINGS)[number]>("unmarked");
  const [waterRating, setWaterRating] = useState<(typeof WATER_RATINGS)[number]>("unmarked");
  const [ventLocks, setVentLocks] = useState<(typeof YES_NO_UNMARKED)[number]>("unmarked");
  const [acousticSeals, setAcousticSeals] = useState<(typeof YES_NO_UNMARKED)[number]>("unmarked");
  const [sumpSills, setSumpSills] = useState<(typeof YES_NO_UNMARKED)[number]>("unmarked");
  const [reveal28, setReveal28] = useState<RevealLining>(EMPTY_REVEAL);
  const [reveal45, setReveal45] = useState<RevealLining>(EMPTY_REVEAL);

  const [buildingType, setBuildingType] = useState<string | null>(null);
  const [construction, setConstruction] = useState<string | null>(null);
  const [floorLevel, setFloorLevel] = useState<string | null>(null);
  const [removeExisting, setRemoveExisting] = useState<string | null>(null);
  const [brickRemovalM2, setBrickRemovalM2] = useState("");
  const [scaffold, setScaffold] = useState<(typeof YES_NO_UNMARKED)[number]>("unmarked");
  const [hoist, setHoist] = useState<(typeof YES_NO_UNMARKED)[number]>("unmarked");
  const [brickSaw, setBrickSaw] = useState<(typeof YES_NO_UNMARKED)[number]>("unmarked");
  const [asbestos, setAsbestos] = useState<(typeof YES_NO_UNMARKED)[number]>("unmarked");
  const [notes, setNotes] = useState("");

  const [items, setItems] = useState<EditableItem[]>([]);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getOwnerQuote(params.quoteId)
      .then((detail: OwnerQuoteDetail) => {
        setClientName(detail.client_name ?? "");
        setClientAddress(detail.header.client_address ?? "");
        setContactName(detail.header.contact_name ?? "");
        setPhone(detail.header.phone ?? "");
        setEmail(detail.header.email ?? "");
        setJobNo(detail.header.job_no ?? "");
        setColour(detail.header.colour ?? "");
        setGlass((detail.header.glass as (typeof GLASS_OPTIONS)[number]) ?? null);
        setWindRating((detail.header.wind_rating as (typeof WIND_RATINGS)[number]) ?? "unmarked");
        setWaterRating((detail.header.water_rating as (typeof WATER_RATINGS)[number]) ?? "unmarked");
        setVentLocks((detail.header.vent_locks as (typeof YES_NO_UNMARKED)[number]) ?? "unmarked");
        setAcousticSeals((detail.header.acoustic_seals as (typeof YES_NO_UNMARKED)[number]) ?? "unmarked");
        setSumpSills((detail.header.sump_sills as (typeof YES_NO_UNMARKED)[number]) ?? "unmarked");
        setBuildingType(detail.installation.building_type);
        setConstruction(detail.installation.construction);
        setFloorLevel(detail.installation.floor_level);
        setRemoveExisting(detail.installation.remove_existing);
        setBrickRemovalM2(detail.installation.brick_removal_m2 != null ? String(detail.installation.brick_removal_m2) : "");
        setScaffold((detail.installation.scaffold as (typeof YES_NO_UNMARKED)[number]) ?? "unmarked");
        setHoist((detail.installation.hoist as (typeof YES_NO_UNMARKED)[number]) ?? "unmarked");
        setBrickSaw((detail.installation.brick_saw as (typeof YES_NO_UNMARKED)[number]) ?? "unmarked");
        setAsbestos((detail.installation.asbestos as (typeof YES_NO_UNMARKED)[number]) ?? "unmarked");
        setNotes(detail.installation.notes ?? "");
        setItems(
          detail.items.map((item) => ({
            item_id: item.item_id,
            delete: false,
            product_type: item.product_type,
            material: item.material,
            room: item.room,
            config_code: item.config_code ?? "",
            qty: String(item.qty),
            width_mm: item.width_mm != null ? String(item.width_mm) : "",
            height_mm: item.height_mm != null ? String(item.height_mm) : "",
            sill_height_mm: item.sill_height_mm != null ? String(item.sill_height_mm) : "",
            glass_spec: item.glass_spec ?? "",
            hardware: item.hardware.join(", "),
            frame_components: item.frame_components.join(", "),
            sealant_and_fixings: item.sealant_and_fixings.join(", "),
            enrichment_notes: item.enrichment_notes ?? "",
          }))
        );
      })
      .catch(() => setLoadError("Couldn't load this job — try again."))
      .finally(() => setLoading(false));
  }, [params.quoteId]);

  const updateItem = (index: number, next: EditableItem) => {
    setItems((prev) => prev.map((it, i) => (i === index ? next : it)));
  };

  const removeItem = (index: number) => {
    setItems((prev) => {
      const item = prev[index];
      if (item.item_id === null) {
        // never persisted — just drop it locally
        return prev.filter((_, i) => i !== index);
      }
      return prev.map((it, i) => (i === index ? { ...it, delete: true } : it));
    });
  };

  const visibleItems = items.filter((it) => !it.delete);

  const onSave = async () => {
    setError(null);
    if (!clientName.trim()) {
      setError("Client name is required.");
      return;
    }
    setSubmitting(true);
    try {
      const itemPayload: OwnerItemEditInput[] = items.map((it) => ({
        item_id: it.item_id,
        delete: it.delete,
        product_type: it.product_type,
        material: it.material,
        room: it.room,
        config_code: it.config_code.trim() || null,
        qty: parseInt(it.qty, 10) || 1,
        width_mm: it.width_mm.trim() ? parseInt(it.width_mm, 10) : null,
        height_mm: it.height_mm.trim() ? parseInt(it.height_mm, 10) : null,
        sill_height_mm: it.sill_height_mm.trim() ? parseInt(it.sill_height_mm, 10) : null,
        glass_spec: it.glass_spec.trim(),
        hardware: it.hardware.split(",").map((s) => s.trim()).filter(Boolean),
        frame_components: it.frame_components.split(",").map((s) => s.trim()).filter(Boolean),
        sealant_and_fixings: it.sealant_and_fixings.split(",").map((s) => s.trim()).filter(Boolean),
        enrichment_notes: it.enrichment_notes.trim() || null,
      }));

      await editQuote(
        params.quoteId,
        {
          client_name: clientName.trim(),
          client_address: clientAddress.trim() || null,
          contact_name: contactName.trim() || null,
          phone: phone.trim() || null,
          email: email.trim() || null,
          job_no: jobNo.trim() || null,
          colour: colour.trim() || null,
          glass: glass || null,
          wind_rating: windRating,
          water_rating: waterRating,
          vent_locks: ventLocks,
          acoustic_seals: acousticSeals,
          sump_sills: sumpSills,
          reveal_28: reveal28,
          reveal_45: reveal45,
        },
        {
          building_type: buildingType,
          construction,
          floor_level: floorLevel,
          remove_existing: removeExisting,
          brick_removal_m2: brickRemovalM2.trim() ? Number(brickRemovalM2) : null,
          scaffold,
          hoist,
          brick_saw: brickSaw,
          asbestos,
          notes,
        },
        itemPayload
      );
      navigation.goBack();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Couldn't save changes — try again.");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <View style={[shared.screen, { justifyContent: "center" }]}>
        <ActivityIndicator />
      </View>
    );
  }

  if (loadError) {
    return (
      <View style={[shared.screen, { justifyContent: "center", padding: 24 }]}>
        <Text style={shared.errorText}>{loadError}</Text>
      </View>
    );
  }

  return (
    <ScrollView style={shared.screen} contentContainerStyle={shared.scrollContent}>
      <Text style={shared.h1}>Edit Quote</Text>

      <View style={shared.card}>
        <Text style={shared.h2}>Customer &amp; Site</Text>
        <View>
          <Text style={shared.label}>Client name *</Text>
          <TextInput style={shared.input} value={clientName} onChangeText={setClientName} />
        </View>
        <View>
          <Text style={shared.label}>Contact name</Text>
          <TextInput style={shared.input} value={contactName} onChangeText={setContactName} />
        </View>
        <View>
          <Text style={shared.label}>Phone</Text>
          <TextInput style={shared.input} value={phone} onChangeText={setPhone} keyboardType="phone-pad" />
        </View>
        <View>
          <Text style={shared.label}>Email</Text>
          <TextInput style={shared.input} value={email} onChangeText={setEmail} autoCapitalize="none" />
        </View>
        <View>
          <AddressAutocomplete value={clientAddress} onChange={setClientAddress} />
        </View>
        <View>
          <Text style={shared.label}>Job number</Text>
          <TextInput style={shared.input} value={jobNo} onChangeText={setJobNo} />
        </View>
      </View>

      <View style={shared.card}>
        <Text style={shared.h2}>Colour &amp; Glass</Text>
        <View>
          <Text style={shared.label}>Colour</Text>
          <TextInput style={shared.input} value={colour} onChangeText={setColour} />
        </View>
        <View>
          <Text style={shared.label}>Glass</Text>
          <ChipPicker options={GLASS_OPTIONS} value={glass} onChange={setGlass} />
        </View>
      </View>

      <View style={shared.card}>
        <Text style={shared.h2}>Compliance Ratings</Text>
        <View>
          <Text style={shared.label}>Wind rating (Pa)</Text>
          <ChipPicker options={WIND_RATINGS} value={windRating} onChange={setWindRating} />
        </View>
        <View>
          <Text style={shared.label}>Water rating (Pa)</Text>
          <ChipPicker options={WATER_RATINGS} value={waterRating} onChange={setWaterRating} />
        </View>
        <View>
          <Text style={shared.label}>Vent locks</Text>
          <ChipPicker options={YES_NO_UNMARKED} value={ventLocks} onChange={setVentLocks} />
        </View>
        <View>
          <Text style={shared.label}>Acoustic seals</Text>
          <ChipPicker options={YES_NO_UNMARKED} value={acousticSeals} onChange={setAcousticSeals} />
        </View>
        <View>
          <Text style={shared.label}>Sump sills</Text>
          <ChipPicker options={YES_NO_UNMARKED} value={sumpSills} onChange={setSumpSills} />
        </View>
      </View>

      <View style={shared.card}>
        <Text style={shared.h2}>Reveal Linings</Text>
        <RevealLiningPicker title="28mm reveal" value={reveal28} onChange={setReveal28} />
        <RevealLiningPicker title="45mm reveal" value={reveal45} onChange={setReveal45} />
      </View>

      <View style={shared.card}>
        <Text style={shared.h2}>Building &amp; Construction</Text>
        <View>
          <Text style={shared.label}>Building type</Text>
          <ChipPicker options={BUILDING_TYPES} value={buildingType} onChange={setBuildingType} />
        </View>
        <View>
          <Text style={shared.label}>Construction</Text>
          <ChipPicker options={CONSTRUCTIONS} value={construction} onChange={setConstruction} />
        </View>
        <View>
          <Text style={shared.label}>Floor level</Text>
          <ChipPicker options={FLOOR_LEVELS} value={floorLevel} onChange={setFloorLevel} />
        </View>
        <View>
          <Text style={shared.label}>Remove existing</Text>
          <ChipPicker options={REMOVE_EXISTING} value={removeExisting} onChange={setRemoveExisting} />
        </View>
        <View>
          <Text style={shared.label}>Brick removal (m²)</Text>
          <TextInput style={shared.input} value={brickRemovalM2} onChangeText={setBrickRemovalM2} keyboardType="decimal-pad" />
        </View>
      </View>

      <View style={shared.card}>
        <Text style={shared.h2}>Equipment Hire</Text>
        <View>
          <Text style={shared.label}>Scaffold</Text>
          <ChipPicker options={YES_NO_UNMARKED} value={scaffold} onChange={setScaffold} />
        </View>
        <View>
          <Text style={shared.label}>Hoist</Text>
          <ChipPicker options={YES_NO_UNMARKED} value={hoist} onChange={setHoist} />
        </View>
        <View>
          <Text style={shared.label}>Brick saw</Text>
          <ChipPicker options={YES_NO_UNMARKED} value={brickSaw} onChange={setBrickSaw} />
        </View>
      </View>

      <View style={shared.card}>
        <Text style={shared.h2}>Site Notes</Text>
        <View>
          <Text style={shared.label}>Asbestos present?</Text>
          <ChipPicker options={YES_NO_UNMARKED} value={asbestos} onChange={setAsbestos} />
        </View>
        <View>
          <Text style={shared.label}>Additional notes</Text>
          <TextInput
            style={[shared.input, { minHeight: 80, textAlignVertical: "top" }]}
            value={notes}
            onChangeText={setNotes}
            multiline
          />
        </View>
      </View>

      <Text style={shared.h2}>Items</Text>
      {items.map((item, index) =>
        item.delete ? null : (
          <ItemEditCard
            key={item.item_id ?? `new-${index}`}
            item={item}
            index={visibleItems.indexOf(item)}
            onChange={(next) => updateItem(index, next)}
            onRemove={() => removeItem(index)}
          />
        )
      )}
      <TouchableOpacity style={shared.buttonSecondary} onPress={() => setItems((prev) => [...prev, blankItem()])}>
        <Text style={shared.buttonSecondaryText}>+ Add Item</Text>
      </TouchableOpacity>

      {error && <Text style={shared.errorText}>{error}</Text>}

      <TouchableOpacity style={shared.button} onPress={onSave} disabled={submitting}>
        {submitting ? <ActivityIndicator color="#fff" /> : <Text style={shared.buttonText}>Save Changes</Text>}
      </TouchableOpacity>
    </ScrollView>
  );
}
