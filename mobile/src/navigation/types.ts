export type RootStackParamList = {
  Login: undefined;
  JobList: undefined;
  PropertyDetails: { quoteId: string };
  Items: { quoteId: string };
  AddItem: { quoteId: string };
  Capture: { quoteId: string; itemId: string; itemLabel: string };
  ReviewSubmit: { quoteId: string };
  QuoteDetail: { quoteId: string };
  OwnerQueue: undefined;
  OwnerQuoteReview: { quoteId: string };
  OwnerEditQuote: { quoteId: string };
  SalesJobList: undefined;
  NewSalesJob: undefined;
  SalesJobDetail: { quoteId: string };
};
