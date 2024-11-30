export interface ApolloError {
  errorCode: number;
  errorType: string;
  errorMessage: string;
  errorDetails?: Record<string, any>;
}

export function isApolloError(value: any): value is ApolloError {
  return (
    value &&
    typeof value.errorCode === 'number' &&
    typeof value.errorType === 'string' &&
    typeof value.errorMessage === 'string'
  );
} 