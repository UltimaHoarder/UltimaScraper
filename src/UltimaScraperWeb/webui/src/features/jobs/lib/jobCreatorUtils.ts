import type { TaskDefinition, TemplateParameterPayload } from '../../../api/types/jobs';

export function parseAuthId(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

export function templateParamToTaskParam(
  parameter: TemplateParameterPayload
): TaskDefinition['parameters'][0] {
  let paramType: TaskDefinition['parameters'][0]['param_type'] = 'text';

  if (parameter.type === 'multiselect') {
    paramType = 'multiselect';
  } else if (parameter.choices && parameter.choices.length > 0) {
    paramType = 'select';
  } else if (parameter.name === 'username') {
    paramType = 'username';
  } else if (parameter.type === 'bool') {
    paramType = 'boolean';
  } else if (parameter.type === 'int' || parameter.type === 'float') {
    paramType = 'number';
  }

  const options = parameter.choices
    ? parameter.choices.map((choice) => ({
        label: String(choice),
        value: String(choice),
      }))
    : [];

  return {
    name: parameter.name,
    label: parameter.name.charAt(0).toUpperCase() + parameter.name.slice(1).replace(/_/g, ' '),
    param_type: paramType,
    required: parameter.required,
    default: parameter.default,
    description: parameter.description,
    options,
    placeholder: parameter.name === 'username' ? 'creator_name' : '',
    min_value: null,
    max_value: null,
  };
}
