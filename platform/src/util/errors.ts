export interface ApolloError {
  code: number;
  type?: string;
  message?: string;
  details?: Record<string, any>;
}

export function isApolloError(value: any): value is ApolloError {
  return value && typeof value.code === 'number';
}
