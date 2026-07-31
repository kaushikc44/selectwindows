import React, { useState } from "react";
import { ActivityIndicator, Text, TextInput, View } from "react-native";
import { TouchableOpacity } from "react-native";

import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { colors, shared } from "../theme";

export default function LoginScreen() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async () => {
    setError(null);
    setSubmitting(true);
    try {
      await login(username.trim(), password);
      // Navigation swaps to the main stack automatically once
      // AuthContext.isLoggedIn flips — see RootNavigator.
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Incorrect username or password.");
      } else {
        setError("Couldn't reach the server — check your connection and try again.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <View style={[shared.screen, { justifyContent: "center", padding: 24 }]}>
      <Text style={[shared.h1, { marginBottom: 24, textAlign: "center" }]}>Select Windows — Field App</Text>

      <View style={{ gap: 16 }}>
        <View>
          <Text style={shared.label}>Username</Text>
          <TextInput
            style={shared.input}
            value={username}
            onChangeText={setUsername}
            autoCapitalize="none"
            autoCorrect={false}
            placeholder="e.g. marcus"
          />
        </View>
        <View>
          <Text style={shared.label}>Password</Text>
          <TextInput
            style={shared.input}
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            placeholder="••••••••"
          />
        </View>

        {error && <Text style={shared.errorText}>{error}</Text>}

        <TouchableOpacity
          style={[shared.button, submitting && { opacity: 0.6 }]}
          onPress={onSubmit}
          disabled={submitting || !username || !password}
        >
          {submitting ? <ActivityIndicator color="#fff" /> : <Text style={shared.buttonText}>Log In</Text>}
        </TouchableOpacity>

        <Text style={[shared.muted, { textAlign: "center" }]}>
          No account? Ask the office to set one up (scripts/create_worker.py).
        </Text>
      </View>
    </View>
  );
}
