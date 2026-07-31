import { StatusBar } from "expo-status-bar";
import React from "react";

import { AuthProvider } from "./src/auth/AuthContext";
import { DraftProvider } from "./src/draft/DraftContext";
import RootNavigator from "./src/navigation/RootNavigator";

export default function App() {
  return (
    <AuthProvider>
      <DraftProvider>
        <RootNavigator />
        <StatusBar style="auto" />
      </DraftProvider>
    </AuthProvider>
  );
}
