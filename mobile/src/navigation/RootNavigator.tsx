import { NavigationContainer } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import React from "react";
import { ActivityIndicator, View } from "react-native";

import { useAuth } from "../auth/AuthContext";
import AddItemScreen from "../screens/AddItemScreen";
import CaptureScreen from "../screens/CaptureScreen";
import ItemsScreen from "../screens/ItemsScreen";
import JobListScreen from "../screens/JobListScreen";
import LoginScreen from "../screens/LoginScreen";
import NewSalesJobScreen from "../screens/NewSalesJobScreen";
import OwnerAiLogsScreen from "../screens/OwnerAiLogsScreen";
import OwnerEditQuoteScreen from "../screens/OwnerEditQuoteScreen";
import OwnerMapScreen from "../screens/OwnerMapScreen";
import OwnerQueueScreen from "../screens/OwnerQueueScreen";
import OwnerQuoteReviewScreen from "../screens/OwnerQuoteReviewScreen";
import PropertyDetailsScreen from "../screens/PropertyDetailsScreen";
import QuoteDetailScreen from "../screens/QuoteDetailScreen";
import ReviewSubmitScreen from "../screens/ReviewSubmitScreen";
import SalesJobDetailScreen from "../screens/SalesJobDetailScreen";
import SalesJobListScreen from "../screens/SalesJobListScreen";
import { colors } from "../theme";
import { RootStackParamList } from "./types";

const Stack = createNativeStackNavigator<RootStackParamList>();

export default function RootNavigator() {
  const { isLoggedIn, isLoading, role } = useAuth();

  if (isLoading) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.paper }}>
        <ActivityIndicator size="large" color={colors.accent} />
      </View>
    );
  }

  return (
    <NavigationContainer>
      <Stack.Navigator screenOptions={{ headerTintColor: colors.accent }}>
        {!isLoggedIn ? (
          <Stack.Screen name="Login" component={LoginScreen} options={{ headerShown: false }} />
        ) : role === "owner" ? (
          // An account is exactly one role — never more than one, so each
          // branch here is a completely separate stack, not extra screens
          // bolted onto another role's flow.
          <>
            <Stack.Screen name="OwnerQueue" component={OwnerQueueScreen} options={{ title: "Review Queue" }} />
            <Stack.Screen name="OwnerMap" component={OwnerMapScreen} options={{ title: "Maps" }} />
            <Stack.Screen name="OwnerAiLogs" component={OwnerAiLogsScreen} options={{ title: "AI Logs" }} />
            <Stack.Screen
              name="OwnerQuoteReview"
              component={OwnerQuoteReviewScreen}
              options={{ title: "Review Job" }}
            />
            <Stack.Screen name="OwnerEditQuote" component={OwnerEditQuoteScreen} options={{ title: "Edit Quote" }} />
          </>
        ) : role === "sales" ? (
          <>
            <Stack.Screen name="SalesJobList" component={SalesJobListScreen} options={{ title: "Job Schedule" }} />
            <Stack.Screen name="NewSalesJob" component={NewSalesJobScreen} options={{ title: "New Job" }} />
            <Stack.Screen
              name="SalesJobDetail"
              component={SalesJobDetailScreen}
              options={{ title: "Job Detail" }}
            />
          </>
        ) : (
          <>
            <Stack.Screen name="JobList" component={JobListScreen} options={{ title: "Field App" }} />
            <Stack.Screen name="PropertyDetails" component={PropertyDetailsScreen} options={{ title: "Property Details" }} />
            <Stack.Screen name="Items" component={ItemsScreen} options={{ title: "Items" }} />
            <Stack.Screen name="AddItem" component={AddItemScreen} options={{ title: "Add Item" }} />
            <Stack.Screen name="Capture" component={CaptureScreen} options={{ title: "Measurements" }} />
            <Stack.Screen name="ReviewSubmit" component={ReviewSubmitScreen} options={{ title: "Review & Submit" }} />
            <Stack.Screen name="QuoteDetail" component={QuoteDetailScreen} options={{ title: "Job Detail" }} />
          </>
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}
