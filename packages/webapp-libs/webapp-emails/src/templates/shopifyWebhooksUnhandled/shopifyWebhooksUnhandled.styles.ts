import styled from 'styled-components';

import { darkModeQuery, emailColors, emailFonts, emailSpacing } from '../../theme';

/** One block per delivery, readable on any screen width. */
export const Delivery = styled.div`
  background-color: ${emailColors.backgroundAlt};
  border: 1px solid ${emailColors.border};
  border-radius: 8px;
  padding: ${emailSpacing.sm};
  margin-bottom: ${emailSpacing.xs};
  font-family: ${emailFonts.primary};
  font-size: ${emailFonts.sizeSm};
  color: ${emailColors.textPrimary};
  text-align: left;

  ${darkModeQuery} {
    background-color: ${emailColors.backgroundDarkAlt} !important;
    border-color: ${emailColors.borderDark} !important;
    color: ${emailColors.textDarkMode} !important;
  }
`;

export const Line = styled.div`
  margin-bottom: 4px;
  word-break: break-word;
`;

export const Label = styled.span`
  font-weight: ${emailFonts.weightSemibold};
`;
