library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL; -- Necesaria para operaciones aritméticas y conversiones

entity contador is
    generic (
        ANCHO_BUS     : integer := 8;   -- Ancho del bus de salida por defecto (8 bits)
        VAL_SATURACION: integer := 255  -- Valor de parada/saturación por defecto
    );
    port (
        clk    : in  std_logic;
        reset  : in  std_logic;
        enable : in  std_logic;
        salida : out std_logic_vector(ANCHO_BUS-1 downto 0)
    );
end entity contador;

architecture Behavioral of contador is
    -- Señal interna de tipo unsigned para poder realizar la suma aritmética
    signal cuenta_reg : unsigned(ANCHO_BUS-1 downto 0);
begin

    process(clk, reset)
    begin
        if reset = '1' then
            -- Inicializa el registro a 0 utilizando la asignación (others => '0')
            cuenta_reg <= (others => '0');
            
        elsif rising_edge(clk) then
            if enable = '1' then
                -- Compara el valor actual con el valor de saturación configurado
                if cuenta_reg = to_unsigned(VAL_SATURACION, ANCHO_BUS) then
                    -- Si alcanza la saturación, mantiene su valor y no sigue contando
                    cuenta_reg <= cuenta_reg;
                else
                    -- Incrementa en 1 si no ha llegado al límite
                    cuenta_reg <= cuenta_reg + 1;
                end if;
            end if;
        end if;
    end process;

    -- Conversión de tipo 'unsigned' a 'std_logic_vector' para la salida final
    salida <= std_logic_vector(cuenta_reg);

end architecture Behavioral;
